[CmdletBinding()]
param([Parameter(Mandatory)][string]$RunRoot, [Parameter(Mandatory)][string]$OutputPath)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
function Assert-Close([double]$Actual, [double]$Expected, [string]$Label) {
    if (-not [double]::IsFinite($Actual) -or [Math]::Abs($Actual - $Expected) -gt 0.0000001) {
        throw "Independent arithmetic mismatch: $Label"
    }
}
$run = Get-Content -LiteralPath (Join-Path $RunRoot 'result.json') -Raw | ConvertFrom-Json
if ($run.state -ne 'COMPLETED' -or $run.windows.Count -ne 4) { throw 'Complete fixed experiment required' }
$cells = @()
foreach ($window in $run.windows) {
    $windowRoot = Join-Path $RunRoot $window.window.id
    $inputs = Get-Content -LiteralPath (Join-Path $windowRoot 'inputs.json') -Raw | ConvertFrom-Json
    foreach ($symbol in @('BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT')) {
        if ($inputs.bars.$symbol.rows -ne 59040 -or $inputs.bars.$symbol.gaps -ne 0 -or
            $inputs.funding.$symbol.rows -ne 123 -or $inputs.funding.$symbol.timestamps_rounded) {
            throw 'Exact full prefix/score/tail coverage required'
        }
    }
    foreach ($arm in $window.arms) {
        $armRoot = Join-Path $windowRoot $arm.arm_id
        $tapePath = Join-Path $armRoot 'decisions.jsonl'
        $tapeHash = (Get-FileHash -LiteralPath $tapePath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($tapeHash -ne $arm.counts.tape_sha256) { throw 'Native tape hash mismatch' }
        foreach ($report in $arm.economic_results) {
            $cost = $report.cost_scenario
            $ledgerPath = Join-Path $armRoot ($cost.id + '-ledger.json')
            $ledger = Get-Content -LiteralPath $ledgerPath -Raw | ConvertFrom-Json
            $entries = @($ledger.events | Where-Object kind -eq 'ENTRY')
            $funding = @($ledger.events | Where-Object kind -eq 'FUNDING')
            $rejected = @($ledger.events | Where-Object kind -eq 'REJECT')
            if ($report.terminal_unresolved_positions.Count -ne 0 -or
                $entries.Count -ne $ledger.trades.Count -or $report.closed_trades -ne $ledger.trades.Count -or
                $entries.Count + $rejected.Count -ne $arm.counts.candidates) { throw 'Candidate/entry/exit mismatch' }
            [double]$netTotal = 0; [double]$entryFees = 0; [double]$exitFees = 0; [double]$carryTotal = 0
            [double]$profit = 0; [double]$loss = 0
            foreach ($trade in $ledger.trades) {
                $sign = if ($trade.side -eq 'LONG') { 1 } elseif ($trade.side -eq 'SHORT') { -1 } else { throw 'Unknown side' }
                $gross = $sign * $trade.quantity * ($trade.exit_price - $trade.entry_price)
                $entryFee = $trade.quantity * $trade.entry_price * $cost.fee_bps_per_side / 10000
                $exitFee = $trade.quantity * $trade.exit_price * $cost.fee_bps_per_side / 10000
                $net = $gross - $entryFee - $exitFee - $trade.signed_funding_cost_usd
                Assert-Close $trade.gross_pnl_usd $gross 'gross'
                Assert-Close $trade.entry_fee_usd $entryFee 'entry fee'
                Assert-Close $trade.exit_fee_usd $exitFee 'exit fee'
                Assert-Close $trade.net_pnl_usd $net 'trade net'
                if ($trade.holding_ms -ne ($trade.exit_ms - $trade.entry_ms) -or $trade.holding_ms -gt 259200000 -or
                    $trade.reason -notin @('SL','TP','TIMEOUT') -or ($trade.entry_ms % 86400000) -ne 3660000) {
                    throw 'Native holding/strict 01:01 entry clock mismatch'
                }
                $netTotal += $net; $entryFees += $entryFee; $exitFees += $exitFee
                $carryTotal += $trade.signed_funding_cost_usd
                if ($net -gt 0) { $profit += $net } else { $loss -= $net }
            }
            foreach ($entry in $entries) {
                if ($entry.reserved_risk_usd -gt $entry.post_entry_equity_usd * 0.0025 + 0.0000001) {
                    throw 'Per-trade admission reservation overrun'
                }
            }
            Assert-Close $report.closed_trade_net_usd $netTotal 'closed total'
            Assert-Close $report.final_equity_usd (10000 + $netTotal) 'account cash'
            Assert-Close $report.net_return_pct ($netTotal / 10000 * 100) 'return'
            Assert-Close $report.total_entry_fees_usd $entryFees 'total entry fees'
            Assert-Close $report.total_exit_fees_usd $exitFees 'total exit fees'
            Assert-Close $report.signed_funding_cost_usd $carryTotal 'funding total'
            [double]$eventCarry = 0; foreach ($event in $funding) { $eventCarry += $event.signed_cost_usd }
            Assert-Close $carryTotal $eventCarry 'funding events reconcile'
            if ($loss -gt 0) { Assert-Close $report.profit_factor ($profit / $loss) 'profit factor' }
            elseif ($null -ne $report.profit_factor) { throw 'Empty-loss PF cannot be finite' }
            if ($report.planning_round_trip_bps -ne $(if ($cost.id -eq 'base') {20} else {33})) {
                throw 'Planning cost assumptions changed'
            }
            $cells += [ordered]@{
                window=$window.window.id; arm=$arm.arm_id; cost=$cost.id; candidates=$arm.counts.candidates
                entries=$entries.Count; closed=$ledger.trades.Count; net_usd=$netTotal
                return_pct=$report.net_return_pct; profit_factor=$report.profit_factor
                mtm_drawdown_pct=$report.closed_minute_mtm_drawdown_pct
                max_mark_risk=$report.max_observed_mark_open_risk_fraction
                risk_mark_overrun=$report.risk_ceiling_mark_overrun
                realized_loss_over_reservation_count=$report.realized_loss_over_reservation_count
                zero_entry_days=$report.zero_entry_days; rejections=$report.admission_rejections
                natural_exits=$report.natural_exit_counts; entries_each_utc_day=$report.entries_each_utc_day
                ledger_sha256=(Get-FileHash -LiteralPath $ledgerPath -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }
    }
}
if ($cells.Count -ne 16) { throw 'All sixteen cells required' }
$receipt = [ordered]@{
    schema='kairos.strategy.independent-ledger-audit.v1'; state='PASSED_SCOPED_ARITHMETIC'
    result_sha256=(Get-FileHash -LiteralPath (Join-Path $RunRoot 'result.json') -Algorithm SHA256).Hash.ToLowerInvariant()
    calculator_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    scope='Independent PowerShell recomputation from retained prices/quantities/fees/carry, not a second economic replay'
    complete_venue_or_alpha_validation=$false; cells=$cells
}
$payload = $receipt | ConvertTo-Json -Depth 12
$stream = [System.IO.File]::Open($OutputPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
try { $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($payload + "`n"); $stream.Write($bytes) }
finally { $stream.Dispose() }
$cells | Format-Table window,arm,cost,candidates,closed,return_pct,profit_factor -AutoSize
