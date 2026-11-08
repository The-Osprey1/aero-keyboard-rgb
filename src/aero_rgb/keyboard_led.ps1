<#
.SYNOPSIS
    GIGABYTE AERO X16 Keyboard LED & Status Indicator Controller
.DESCRIPTION
    Controls the keyboard RGB LED array and status indicators on GIGABYTE AERO / AORUS laptops
    via the internal hardware lighting controller.
.NOTES
    Normally called by the aero-rgb Python tool. Can also be run on its own.
.EXAMPLE
    .\keyboard_led.ps1 -Color Cyan -Pattern Breathe
    .\keyboard_led.ps1 -Status busy
    .\keyboard_led.ps1 -Color "#FF5500" -Brightness 5
    .\keyboard_led.ps1 -Status restore
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("Static", "Still", "Breathe", "Pulse", "Cycle", "Rainbow", "RgbPulse", "CyclePulse")]
    [string]$Pattern = "Static",

    [Parameter(Position = 1)]
    [string]$Color = "White",

    [Parameter()]
    [ValidateRange(0, 10)]
    [int]$Brightness = 7,

    [Parameter()]
    [ValidateRange(1, 10)]
    [int]$Speed = 8,

    [Parameter()]
    [ValidateSet("normal", "idle", "busy", "building", "success", "pass", "warning", "error", "fail", "focus", "rainbow", "off", "restore")]
    [string]$Status,

    [Parameter()]
    [ValidateRange(1, 8)]
    [int]$Zone = 1,

    [Parameter()]
    [switch]$Quiet
)

# Color name mapping table
$ColorMap = @{
    "black"      = 0x000000
    "off"        = 0x000000
    "white"      = 0xFFFFFF
    "warmwhite"  = 0xFFE4B5
    "red"        = 0xFF0000
    "crimson"    = 0xDC143C
    "green"      = 0x00FF00
    "lime"       = 0x32CD32
    "blue"       = 0x0066FF
    "deepblue"   = 0x0000FF
    "cyan"       = 0x00FFFF
    "teal"       = 0x008080
    "magenta"    = 0xFF00FF
    "purple"     = 0x8A2BE2
    "yellow"     = 0xFFFF00
    "gold"       = 0xFFD700
    "orange"     = 0xFF6600
    "amber"      = 0xFFBF00
    "pink"       = 0xFF69B4
}

function Resolve-ColorValue([string]$col) {
    $c = $col.Trim().ToLower()
    if ($ColorMap.ContainsKey($c)) {
        return $ColorMap[$c]
    }
    if ($c.StartsWith("#")) {
        $c = $c.Substring(1)
    } elseif ($c.StartsWith("0x")) {
        $c = $c.Substring(2)
    }
    try {
        return [System.Convert]::ToInt32($c, 16)
    } catch {
        Write-Warning "Unknown color '$col', defaulting to White (0xFFFFFF)"
        return 0xFFFFFF
    }
}

# Process Status Presets
if ($PSBoundParameters.ContainsKey("Status")) {
    switch ($Status.ToLower()) {
        { $_ -in "normal", "idle" } {
            $Pattern = "Static"
            $Color = "White"
            $Brightness = 6
        }
        { $_ -in "busy", "building" } {
            $Pattern = "Breathe"
            $Color = "Cyan"
            $Speed = 8
            $Brightness = 8
        }
        { $_ -in "success", "pass" } {
            $Pattern = "Breathe"
            $Color = "Green"
            $Speed = 6
            $Brightness = 9
        }
        { $_ -in "warning" } {
            $Pattern = "Breathe"
            $Color = "Amber"
            $Speed = 7
            $Brightness = 8
        }
        { $_ -in "error", "fail" } {
            $Pattern = "Breathe"
            $Color = "Red"
            $Speed = 9
            $Brightness = 10
        }
        "focus" {
            $Pattern = "Static"
            $Color = "WarmWhite"
            $Brightness = 3
        }
        "rainbow" {
            $Pattern = "Cycle"
            $Speed = 6
            $Brightness = 8
        }
        "off" {
            $Pattern = "Static"
            $Color = "Black"
            $Brightness = 0
        }
        "restore" {
            $Pattern = "Static"
            $Color = "White"
            $Brightness = 7
        }
    }
}

# Map Pattern to Hardware Mode ID
$pattId = 0
switch ($Pattern.ToLower()) {
    "static"     { $pattId = 0 }
    "breathe"    { $pattId = 1 }
    "pulse"      { $pattId = 1 }
    "cycle"      { $pattId = 78 }
    "rainbow"    { $pattId = 78 }
    "still"      { $pattId = 0 }
    "rgbpulse"   { $pattId = 84 }
    "cyclepulse" { $pattId = 92 }
}

$colorInt = Resolve-ColorValue $Color

# Load Gigabyte Controller assemblies
$commDir = "C:\Program Files\GIGABYTE\Control Center\Lib\COMMDLL"
$ucDir   = "C:\Program Files\GIGABYTE\Control Center\Lib\GBT_rgbLaptop_UC"

if (-not (Test-Path "$commDir\RGBFI.dll") -or -not (Test-Path "$ucDir\RgbLaptop.dll")) {
    Write-Error "Gigabyte Control Center libraries not found on this system."
    exit 1
}

[System.Reflection.Assembly]::Load([System.IO.File]::ReadAllBytes("$commDir\RGBFI.dll")) | Out-Null
$commonAsm = [System.Reflection.Assembly]::Load([System.IO.File]::ReadAllBytes("$commDir\RgbCommon.dll"))
$ucAsm     = [System.Reflection.Assembly]::Load([System.IO.File]::ReadAllBytes("$ucDir\RgbLaptop.dll"))

$controllerType = $ucAsm.GetType("RgbLaptop.RGB_Laptop")
$controller = [System.Activator]::CreateInstance($controllerType)

# Initialize hardware connection
$initMethod = $controllerType.GetMethod("Initial", [System.Reflection.BindingFlags]'Public,NonPublic,Instance,Static')
$initSuccess = $initMethod.Invoke($controller, $null)

if (-not $initSuccess) {
    Write-Error "Failed to initialize connection to keyboard MCU controller."
    exit 1
}

# Construct RGB command packet
$paramType = $commonAsm.GetType("RgbCommon.RGBParamF1")
$param = [System.Activator]::CreateInstance($paramType)
$cmdType = $commonAsm.GetType("RgbCommon.CmdFormat1")
$cmd = [System.Activator]::CreateInstance($cmdType)

$cmd.patt = [byte]$pattId
$cmd.bri = [byte]$Brightness
$cmd.speed = [byte]$Speed
$cmd.clr_idx = [byte]0

$param.rgb_zone = $Zone
$param.rgb_color = $colorInt
$param.cmd = $cmd

$setZoneMethod = $controllerType.GetMethod("set_RgbZoneEff", [System.Reflection.BindingFlags]'Public,NonPublic,Instance,Static')
$result = $setZoneMethod.Invoke($controller, @($param))

if ($result -eq 0 -and $Quiet) {
    exit 0
} elseif ($result -eq 0) {
    Write-Host "Keyboard LED successfully updated:" -ForegroundColor Green
    Write-Host "  Pattern:    $Pattern ($pattId)"
    Write-Host "  Color:      $Color (0x$($colorInt.ToString('X6')))"
    Write-Host "  Brightness: $Brightness/10"
    Write-Host "  Speed:      $Speed/10"
    Write-Host "  Zone:       $Zone"
} else {
    Write-Error "Hardware returned status code: $result"
    exit 2
}
