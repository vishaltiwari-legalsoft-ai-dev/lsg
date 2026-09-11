# schedule_windows.ps1 -- GENERATOR ONLY. Prints the `schtasks /Create`
# commands that WOULD register context/40-pipeline/06-orchestration.md's
# cron table (as mirrored in config/schedule.yml -- that file, and
# `uv run lge schedule`, are the source of truth for cadence text; the rows
# below are kept in sync with it by hand) as Windows Scheduled Tasks.
#
# This script never calls schtasks.exe, Start-Process, Invoke-Expression, or
# anything else that would register a task -- every line below only builds
# and Write-Output's a string. Registering a task on this machine is a
# decision for a person to make deliberately: copy the printed command you
# want and run it yourself, after checking the [PLACEHOLDER] ones name
# components that do not exist in this checkout yet.
#
# Each generated command's action starts the portable Postgres
# (scripts/pg.sh) before running the `lge` command, per the M10 build
# brief -- NOT because this session's already-running server should ever be
# stopped or restarted (it must not be), but because a real scheduled task
# on this machine may run at a time nothing else has started Postgres yet.
# pg.sh is expected to be a no-op / safe to call again if the server it
# manages is already up.
#
# Nested quoting note: the printed /TR values are illustrative, not
# certified-correct for every shell -- Windows Task Scheduler's own
# cmd.exe-inside-schtasks quoting is notoriously fragile once a path has
# spaces (this project's root does). Review and adjust quoting for your
# shell before pasting any of these; that is exactly why this script prints
# rather than runs them.
#
# Usage (never run automatically by anything in this repo):
#   powershell -NoProfile -File scripts\schedule_windows.ps1

$ErrorActionPreference = 'Stop'

$ProjectRoot = 'C:\Users\ACER\Desktop\Lead Gen Engine'

# Mirrors config/schedule.yml. kind: 'flow' -> `lge flow <job>`,
# kind: 'component' -> `lge run <job>`. `Placeholder` rows name a component
# that is not registered in this checkout yet (see config/schedule.yml for
# why each one is still listed).
$ScheduleRows = @(
  @{ Id = 'nightly';               Kind = 'flow';      Job = 'nightly';               Cadence = 'DAILY';   Time = '02:00'; Placeholder = $false }
  @{ Id = 'bench_sync_hourly';     Kind = 'component'; Job = 'bench_sync';             Cadence = 'HOURLY';  Time = $null;   Placeholder = $false }
  @{ Id = 'i3_portal_demand';      Kind = 'component'; Job = 'i3';                     Cadence = 'HOURLY';  Time = $null;   Placeholder = $true  }
  @{ Id = 'i4_talent_pool';        Kind = 'component'; Job = 'i4';                     Cadence = 'HOURLY';  Time = $null;   Placeholder = $true  }
  @{ Id = 'w3_review_poller';      Kind = 'component'; Job = 'w3';                     Cadence = 'WEEKLY';  Day  = 'SUN';   Placeholder = $true  }
  @{ Id = 'ja5_serp_discovery';    Kind = 'component'; Job = 'ja5';                    Cadence = 'WEEKLY';  Day  = $null;   Placeholder = $true  }
  @{ Id = 'observe_robots_reaudit';Kind = 'component'; Job = 'observe_robots_reaudit'; Cadence = 'WEEKLY';  Day  = $null;   Placeholder = $true  }
  @{ Id = 'w4_w5_ads_mass_tort';   Kind = 'component'; Job = 'w4_w5';                  Cadence = 'MONTHLY'; Day  = '1';     Placeholder = $true  }
  @{ Id = 'w6_tech_delta';         Kind = 'component'; Job = 'w6';                     Cadence = 'QUARTERLY'; Placeholder = $true }
  @{ Id = 'w7_liveness';           Kind = 'component'; Job = 'w7';                     Cadence = 'ROLLING'; Placeholder = $true  }
)

function Get-LgeAction {
  param([string]$Kind, [string]$Job)
  $lgeCmd = if ($Kind -eq 'flow') { "uv run lge flow $Job" } else { "uv run lge run $Job" }
  # /c takes the REST of the line as one command string passed to cmd.exe.
  return "cmd.exe /c `"cd /d ""$ProjectRoot"" && bash scripts\pg.sh && $lgeCmd`""
}

function Get-SchtasksCommand {
  param([hashtable]$Row)

  $taskName = "LGE_$($Row.Id)"
  $action = Get-LgeAction -Kind $Row.Kind -Job $Row.Job

  switch ($Row.Cadence) {
    'DAILY' {
      return "schtasks /Create /TN `"$taskName`" /SC DAILY /ST $($Row.Time) /TR `"$action`" /F"
    }
    'HOURLY' {
      return "schtasks /Create /TN `"$taskName`" /SC HOURLY /MO 1 /TR `"$action`" /F"
    }
    'WEEKLY' {
      $dayArg = if ($Row.Day) { "/D $($Row.Day)" } else { '' }
      return "schtasks /Create /TN `"$taskName`" /SC WEEKLY $dayArg /ST 03:00 /TR `"$action`" /F".Replace('  ', ' ')
    }
    'MONTHLY' {
      return "schtasks /Create /TN `"$taskName`" /SC MONTHLY /D $($Row.Day) /ST 03:00 /TR `"$action`" /F"
    }
    'QUARTERLY' {
      # schtasks has no native quarterly cadence -- MONTHLY with an explicit
      # month list approximates it. Approximate on purpose; adjust the month
      # list to when W6 should actually run before using this one.
      return "schtasks /Create /TN `"$taskName`" /SC MONTHLY /M JAN,APR,JUL,OCT /D 1 /ST 03:00 /TR `"$action`" /F"
    }
    'ROLLING' {
      return $null  # no cron-shaped cadence -- see the note printed below instead.
    }
    default {
      return $null
    }
  }
}

Write-Output '# ============================================================'
Write-Output '# schedule_windows.ps1 -- commands that WOULD register these.'
Write-Output '# Nothing above this point, or below, has been executed.'
Write-Output '# ============================================================'
Write-Output ''

foreach ($row in $ScheduleRows) {
  $flag = if ($row.Placeholder) { '  [PLACEHOLDER -- component not registered in this build yet]' } else { '' }
  Write-Output "# --- $($row.Id)$flag"

  if ($row.Cadence -eq 'ROLLING') {
    Write-Output "#     ROLLING cadence (1/90th of the universe per day) has no schtasks"
    Write-Output "#     equivalent -- it needs a script that tracks WHICH 1/90th ran last,"
    Write-Output "#     not just a fixed time. Not generated here."
    Write-Output ''
    continue
  }

  $cmd = Get-SchtasksCommand -Row $row
  if ($null -ne $cmd) {
    Write-Output $cmd
  }
  Write-Output ''
}

Write-Output '# To actually register one of these, copy its command and run it yourself.'
Write-Output '# To remove a task registered this way: schtasks /Delete /TN "LGE_<id>" /F'
