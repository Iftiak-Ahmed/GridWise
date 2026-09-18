# Manual test template — edit operator_notes below to try your own phrasing, then run:
#   .\tests\manual_test.ps1
# This sends ONE request to the LIVE endpoint, exactly like a judge's hidden test would.

$body = @{
    scenario_id    = "MANUAL-TEST-01"
    operator_notes = @(
        "Battery discharge is off between 3pm and 5pm for a safety check."
        # <-- change this line to whatever phrasing you want to test.
        # Try paraphrasing a directive differently: 24-hour clock, percentages,
        # "half"/"a quarter" instead of numbers, different verbs, etc.
    )
    hours          = @(
        @{ hour = 0;  demand_kwh = 90;  solar_kwh = 0;   tariff_bdt_per_kwh = 6 }
        @{ hour = 1;  demand_kwh = 85;  solar_kwh = 0;   tariff_bdt_per_kwh = 6 }
        @{ hour = 2;  demand_kwh = 80;  solar_kwh = 0;   tariff_bdt_per_kwh = 5 }
        @{ hour = 3;  demand_kwh = 80;  solar_kwh = 0;   tariff_bdt_per_kwh = 5 }
        @{ hour = 4;  demand_kwh = 85;  solar_kwh = 0;   tariff_bdt_per_kwh = 5 }
        @{ hour = 5;  demand_kwh = 95;  solar_kwh = 0;   tariff_bdt_per_kwh = 6 }
        @{ hour = 6;  demand_kwh = 110; solar_kwh = 5;   tariff_bdt_per_kwh = 8 }
        @{ hour = 7;  demand_kwh = 130; solar_kwh = 20;  tariff_bdt_per_kwh = 10 }
        @{ hour = 8;  demand_kwh = 150; solar_kwh = 50;  tariff_bdt_per_kwh = 12 }
        @{ hour = 9;  demand_kwh = 165; solar_kwh = 90;  tariff_bdt_per_kwh = 14 }
        @{ hour = 10; demand_kwh = 175; solar_kwh = 130; tariff_bdt_per_kwh = 16 }
        @{ hour = 11; demand_kwh = 180; solar_kwh = 160; tariff_bdt_per_kwh = 16 }
        @{ hour = 12; demand_kwh = 185; solar_kwh = 180; tariff_bdt_per_kwh = 15 }
        @{ hour = 13; demand_kwh = 180; solar_kwh = 170; tariff_bdt_per_kwh = 14 }
        @{ hour = 14; demand_kwh = 170; solar_kwh = 140; tariff_bdt_per_kwh = 13 }
        @{ hour = 15; demand_kwh = 165; solar_kwh = 90;  tariff_bdt_per_kwh = 14 }
        @{ hour = 16; demand_kwh = 170; solar_kwh = 45;  tariff_bdt_per_kwh = 18 }
        @{ hour = 17; demand_kwh = 185; solar_kwh = 10;  tariff_bdt_per_kwh = 22 }
        @{ hour = 18; demand_kwh = 205; solar_kwh = 0;   tariff_bdt_per_kwh = 28 }
        @{ hour = 19; demand_kwh = 215; solar_kwh = 0;   tariff_bdt_per_kwh = 30 }
        @{ hour = 20; demand_kwh = 205; solar_kwh = 0;   tariff_bdt_per_kwh = 26 }
        @{ hour = 21; demand_kwh = 175; solar_kwh = 0;   tariff_bdt_per_kwh = 18 }
        @{ hour = 22; demand_kwh = 135; solar_kwh = 0;   tariff_bdt_per_kwh = 10 }
        @{ hour = 23; demand_kwh = 105; solar_kwh = 0;   tariff_bdt_per_kwh = 7 }
    )
    battery        = @{
        capacity_kwh              = 220
        initial_energy_kwh        = 110
        minimum_energy_kwh        = 40
        max_charge_kwh_per_hour   = 50
        max_discharge_kwh_per_hour = 50
    }
} | ConvertTo-Json -Depth 6

$url = "https://gridwise-optimizer.onrender.com/optimize-energy"
Write-Output "Sending request to $url ..."
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$response = Invoke-RestMethod -Uri $url -Method Post -Body $body -ContentType "application/json"
$sw.Stop()

Write-Output "`nElapsed: $($sw.Elapsed.TotalSeconds)s`n"
Write-Output "--- directive_interpretation (did it understand your note correctly?) ---"
$response.directive_interpretation | ConvertTo-Json -Depth 5
Write-Output "`n--- totals ---"
Write-Output "total_cost_bdt: $($response.total_cost_bdt)"
Write-Output "total_grid_kwh: $($response.total_grid_kwh)"
Write-Output "peak_grid_kwh: $($response.peak_grid_kwh)"
Write-Output "`nplan_summary: $($response.plan_summary)"
