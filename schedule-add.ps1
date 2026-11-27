$taskName   = "kk-GuelphParksLayer"
$projectDir = $PSScriptRoot
$logFile    = "$projectDir\logs\scheduler.log"

if (-not (Test-Path "$projectDir\logs")) {
    New-Item -ItemType Directory -Path "$projectDir\logs" | Out-Null
}

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"`"$projectDir\run-scheduled.cmd`" >> `"$logFile`" 2>&1`""

# Daily, though 126 park polygons change rarely: what moves is the gap page,
# which diffs against live OSM, and a day-old page is what mappers want after an
# evening's edits. A day with no City change costs nothing extra -- the download
# keeps the existing dated file when the features hash the same, and history
# replaces a same-day row rather than adding one.
#
# 21:15, not 16:30: the siblings each hold a weekly 16:30 or 19:30 slot
# (buildings, bus stops, hydrants, sidewalks, trees; water, gardens, poster
# columns, bike) so no two drive tippecanoe in the same WSL instance at once. A
# daily run at either hour would land on all of them. 21:15 is clear of the
# 19:30 retries (last at 21:00) and its own retries end by 22:45. Sidewalks held
# this daily slot from 2026-11-17 to 2026-11-27.
$trigger  = New-ScheduledTaskTrigger -Daily -At "21:15"
# Retries live in run-scheduled.cmd, not here: 'update' exits 75 when it sees no
# usable link, and 70 when no Overpass mirror answered and the gap page fell back
# to cached OSM (published first). The wrapper tries either again up to twice, half
# an hour apart, and the 3-hour limit leaves room for that. RestartCount covers only
# a launch that fails; Task Scheduler never re-runs on an exit code.
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 3) -StartWhenAvailable `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 30)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force

Write-Host "Scheduled '$taskName' to run daily at 21:15."
Write-Host "Log: $logFile"
