<#
.SYNOPSIS
  Legt die Windows-Firewallregel fuer den Tapesmith-Druckdienst (p12d) im LAN an, prueft oder entfernt sie.

.DESCRIPTION
  Einmaliger Admin-Schritt fuer die LAN-Freigabe. Die App selbst aendert
  nie die Firewall. Das Skript ist idempotent: fehlt die Regel, wird sie angelegt; weicht sie ab,
  werden nur die abweichenden Werte gesetzt; stimmt alles, aendert es nichts.

  Die Regel erlaubt nur eingehendes TCP auf dem Port des Druckdienstes (Standard 8712), nur aus den
  angegebenen privaten IPv4-Netzen (Standard 192.168.0.0/16) und nur in den Profilen Privat und
  Domaene. Sie nennt bewusst kein Programm (der Python-Pfad aendert sich mit venv bzw. portabler
  Version); die Begrenzung erfolgt ueber Port und Remote-Adresse.

  Anlegen, Aendern und Entfernen brauchen Administratorrechte. -Status geht ohne.
  Am Ende zeigt das Skript immer den Status und die naechsten Schritte.

.PARAMETER Port
  TCP-Port des Druckdienstes (Konfiguration web.port), Standard 8712.

.PARAMETER RemoteAddress
  Erlaubte Quellnetze als private IPv4-CIDR (10/8, 172.16/12, 192.168/16, Praefix mindestens 8).
  Standard 192.168.0.0/16.

.PARAMETER FirewallProfile
  Firewallprofile der Regel, Standard Private und Domain.

.PARAMETER Status
  Nur den Status anzeigen (Regel, Filter, lauschende Adressen). Braucht keine Adminrechte.

.PARAMETER Remove
  Regel entfernen, falls vorhanden.

.EXAMPLE
  .\setup-tapesmith-lan.ps1 -Status

.EXAMPLE
  .\setup-tapesmith-lan.ps1

.EXAMPLE
  .\setup-tapesmith-lan.ps1 -RemoteAddress 192.168.1.0/24, 10.10.0.0/16

.EXAMPLE
  .\setup-tapesmith-lan.ps1 -Remove
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateRange(1024, 65535)][int]$Port = 8712,
    [string[]]$RemoteAddress = @('192.168.0.0/16'),
    [ValidateSet('Private', 'Domain', 'Public')][string[]]$FirewallProfile = @('Private', 'Domain'),
    [switch]$Status,
    [switch]$Remove
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RuleName = "Tapesmith-LAN-TCP-$Port"
$RuleDisplayName = "Tapesmith Druckdienst (TCP $Port, LAN)"
$RuleGroup = 'Tapesmith'
$RuleDescription = "Erlaubt Zugriffe aus dem LAN auf den Tapesmith-Druckdienst (p12d, Port $Port). Angelegt von setup-tapesmith-lan.ps1."

function ConvertTo-AddressValue {
    <# IPv4-Adresse als Zahl (int64, 0 bis 2^32-1). #>
    param([Parameter(Mandatory)][System.Net.IPAddress]$Address)
    $bytes = $Address.GetAddressBytes()
    return ([int64]$bytes[0] * 16777216) + ([int64]$bytes[1] * 65536) + ([int64]$bytes[2] * 256) + [int64]$bytes[3]
}

function Get-BlockSize {
    <# Anzahl Adressen eines Netzes mit diesem Praefix (2 hoch (32 minus Praefix)). #>
    param([Parameter(Mandatory)][int]$Prefix)
    return [int64][math]::Pow(2, 32 - $Prefix)
}

function Get-PrefixFromMask {
    <# Praefixlaenge einer Netzmaske (255.255.255.0 ergibt 24), -1 bei ungueltiger Maske. #>
    param([Parameter(Mandatory)][System.Net.IPAddress]$Mask)
    $value = ConvertTo-AddressValue -Address $Mask
    for ($prefix = 0; $prefix -le 32; $prefix++) {
        if ($value -eq ([int64]4294967296 - (Get-BlockSize -Prefix $prefix))) { return $prefix }
    }
    return -1
}

function ConvertTo-NormalizedCidr {
    <# Liefert "Netz/Praefix" (z. B. 192.168.1.0/24) oder $null, wenn der Text kein IPv4-Netz ist.
       Versteht "a.b.c.d/nn" und die Windows-Form "a.b.c.d/255.255.255.0". #>
    param([Parameter(Mandatory)][string]$Text)
    $parts = $Text.Trim().Split('/')
    if ($parts.Count -ne 2) { return $null }
    if ($parts[0] -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { return $null }
    $ip = $null
    if (-not [System.Net.IPAddress]::TryParse($parts[0], [ref]$ip)) { return $null }
    $prefix = -1
    if ($parts[1] -match '^\d{1,2}$') {
        $prefix = [int]$parts[1]
    } elseif ($parts[1] -match '^\d{1,3}(\.\d{1,3}){3}$') {
        $mask = $null
        if (-not [System.Net.IPAddress]::TryParse($parts[1], [ref]$mask)) { return $null }
        $prefix = Get-PrefixFromMask -Mask $mask
    }
    if ($prefix -lt 0 -or $prefix -gt 32) { return $null }
    $value = ConvertTo-AddressValue -Address $ip
    $network = $value - ($value % (Get-BlockSize -Prefix $prefix))
    $octets = @(
        ([math]::Floor($network / 16777216) % 256),
        ([math]::Floor($network / 65536) % 256),
        ([math]::Floor($network / 256) % 256),
        ($network % 256)
    )
    return ('{0}/{1}' -f ($octets -join '.'), $prefix)
}

function Test-PrivateCidr {
    <# Prueft ein normalisiertes Netz: privat (10/8, 172.16/12, 192.168/16) und Praefix mindestens 8. #>
    param([Parameter(Mandatory)][string]$Cidr)
    $parts = $Cidr.Split('/')
    $prefix = [int]$parts[1]
    if ($prefix -lt 8) { return $false }
    $value = ConvertTo-AddressValue -Address ([System.Net.IPAddress]::Parse($parts[0]))
    $ranges = @(
        @{ Base = '10.0.0.0'; Prefix = 8 },
        @{ Base = '172.16.0.0'; Prefix = 12 },
        @{ Base = '192.168.0.0'; Prefix = 16 }
    )
    foreach ($range in $ranges) {
        if ($prefix -lt $range.Prefix) { continue }
        $block = Get-BlockSize -Prefix $range.Prefix
        $base = ConvertTo-AddressValue -Address ([System.Net.IPAddress]::Parse($range.Base))
        if ([math]::Floor($value / $block) -eq [math]::Floor($base / $block)) { return $true }
    }
    return $false
}

function Test-IsAdministrator {
    $principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-P12Rule {
    return Get-NetFirewallRule -Name $RuleName -ErrorAction SilentlyContinue
}

function Get-ProfileList {
    param([Parameter(Mandatory)]$Rule)
    return @(($Rule.Profile.ToString() -split ',\s*') | Where-Object { $_ } | Sort-Object)
}

function Get-RuleAddressList {
    param([Parameter(Mandatory)]$Rule)
    $filter = Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $Rule
    $result = @()
    foreach ($entry in @($filter.RemoteAddress)) {
        $normalized = ConvertTo-NormalizedCidr -Text ([string]$entry)
        if ($normalized) { $result += $normalized } else { $result += [string]$entry }
    }
    return @($result | Sort-Object -Unique)
}

function Show-P12Status {
    Write-Host ''
    Write-Host "Status Firewallregel $RuleName"
    $rule = Get-P12Rule
    if (-not $rule) {
        Write-Host '  Regel: nicht vorhanden'
    } else {
        $portFilter = Get-NetFirewallPortFilter -AssociatedNetFirewallRule $rule
        Write-Host ('  Regel:        vorhanden ({0})' -f $rule.DisplayName)
        Write-Host ('  Aktiviert:    {0}' -f $rule.Enabled)
        Write-Host ('  Richtung:     {0}' -f $rule.Direction)
        Write-Host ('  Aktion:       {0}' -f $rule.Action)
        Write-Host ('  Protokoll:    {0}' -f $portFilter.Protocol)
        Write-Host ('  Port:         {0}' -f (@($portFilter.LocalPort) -join ', '))
        Write-Host ('  Quellnetze:   {0}' -f ((Get-RuleAddressList -Rule $rule) -join ', '))
        Write-Host ('  Profile:      {0}' -f ((Get-ProfileList -Rule $rule) -join ', '))
    }
    $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -eq 0) {
        Write-Host "  Druckdienst:  lauscht nicht auf Port $Port (p12d gestartet?)"
    } else {
        $addresses = @($listeners | ForEach-Object { '{0}:{1}' -f $_.LocalAddress, $_.LocalPort } | Sort-Object -Unique)
        Write-Host ('  Druckdienst:  lauscht auf {0}' -f ($addresses -join ', '))
        if (-not ($listeners | Where-Object { $_.LocalAddress -ne '127.0.0.1' -and $_.LocalAddress -ne '::1' })) {
            Write-Host '                nur localhost: im LAN erst nach lan.enabled = true und Dienst-Neustart erreichbar'
        }
    }
    Write-Host '  Hinweis: Die App bindet nur ans LAN, wenn lan.enabled in config.json an ist.'
}

function Show-NextSteps {
    Write-Host ''
    Write-Host 'Naechste Schritte:'
    Write-Host '  1. p12 config set lan.enabled true'
    Write-Host '  2. p12 daemon restart'
    Write-Host "  3. Von einem Geraet im Netz testen: http://<PC-IP>:$Port/health"
    Write-Host '  Rueckbau: setup-tapesmith-lan.ps1 -Remove und p12 config set lan.enabled false'
}

# Quellnetze pruefen (nie Any, nur private IPv4-Netze).
$normalizedAddresses = @()
foreach ($entry in $RemoteAddress) {
    $normalized = ConvertTo-NormalizedCidr -Text $entry
    if (-not $normalized -or -not (Test-PrivateCidr -Cidr $normalized)) {
        Write-Host ("Ungültiges Quellnetz '{0}': erlaubt sind nur private IPv4-Netze in CIDR-Form (10/8, 172.16/12, 192.168/16, Präfix mindestens 8), z. B. 192.168.1.0/24." -f $entry)
        exit 1
    }
    $normalizedAddresses += $normalized
}
$normalizedAddresses = @($normalizedAddresses | Sort-Object -Unique)
$wantedProfiles = @($FirewallProfile | Sort-Object -Unique)

if ($Status) {
    Show-P12Status
    Show-NextSteps
    exit 0
}

if (-not (Test-IsAdministrator)) {
    Write-Host 'Bitte als Administrator ausführen (Rechtsklick, Als Administrator ausführen) oder nur -Status verwenden.'
    exit 1
}

if ($Remove) {
    $rule = Get-P12Rule
    if (-not $rule) {
        Write-Host "Regel $RuleName ist nicht vorhanden, nichts zu entfernen."
    } elseif ($PSCmdlet.ShouldProcess($RuleDisplayName, 'Firewallregel entfernen')) {
        Remove-NetFirewallRule -Name $RuleName
        Write-Host "Regel $RuleName entfernt."
    }
    Show-P12Status
    exit 0
}

$rule = Get-P12Rule
if (-not $rule) {
    if ($PSCmdlet.ShouldProcess($RuleDisplayName, 'Firewallregel anlegen')) {
        New-NetFirewallRule -Name $RuleName -DisplayName $RuleDisplayName -Group $RuleGroup `
            -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port `
            -RemoteAddress $normalizedAddresses -Profile $wantedProfiles `
            -Description $RuleDescription | Out-Null
        Write-Host "Regel $RuleName angelegt."
    }
} else {
    $changed = $false
    $portFilter = Get-NetFirewallPortFilter -AssociatedNetFirewallRule $rule
    $currentPorts = @(@($portFilter.LocalPort) | ForEach-Object { [string]$_ })
    if ([string]$portFilter.Protocol -ne 'TCP' -or ($currentPorts -join ',') -ne [string]$Port) {
        if ($PSCmdlet.ShouldProcess($RuleDisplayName, "Protokoll TCP und Port $Port setzen")) {
            Set-NetFirewallPortFilter -InputObject $portFilter -Protocol TCP -LocalPort $Port
            $changed = $true
        }
    }
    $currentAddresses = Get-RuleAddressList -Rule $rule
    if (($currentAddresses -join ',') -ne ($normalizedAddresses -join ',')) {
        if ($PSCmdlet.ShouldProcess($RuleDisplayName, ('Quellnetze auf {0} setzen' -f ($normalizedAddresses -join ', ')))) {
            $addressFilter = Get-NetFirewallAddressFilter -AssociatedNetFirewallRule $rule
            Set-NetFirewallAddressFilter -InputObject $addressFilter -RemoteAddress $normalizedAddresses
            $changed = $true
        }
    }
    $currentProfiles = Get-ProfileList -Rule $rule
    $ruleSettingsDiffer = (
        [string]$rule.Direction -ne 'Inbound' -or
        [string]$rule.Action -ne 'Allow' -or
        ($currentProfiles -join ',') -ne ($wantedProfiles -join ',') -or
        $rule.DisplayName -ne $RuleDisplayName
    )
    if ($ruleSettingsDiffer) {
        if ($PSCmdlet.ShouldProcess($RuleDisplayName, 'Richtung, Aktion, Profile und Namen setzen')) {
            Set-NetFirewallRule -Name $RuleName -Direction Inbound -Action Allow -Profile $wantedProfiles `
                -NewDisplayName $RuleDisplayName -Description $RuleDescription
            $changed = $true
        }
    }
    if ([string]$rule.Enabled -ne 'True') {
        if ($PSCmdlet.ShouldProcess($RuleDisplayName, 'Firewallregel aktivieren')) {
            Enable-NetFirewallRule -Name $RuleName
            $changed = $true
        }
    }
    if ($changed) {
        Write-Host "Regel $RuleName aktualisiert."
    } else {
        Write-Host 'Regel ist aktuell, nichts geändert.'
    }
}

Show-P12Status
Show-NextSteps
exit 0
