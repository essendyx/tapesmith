#Requires -Version 5.1
<#
    Tapesmith: PowerShell-Modul für die Automatisierung des Phomemo-P12-Labeldruckers aus der
    Konsole. Spricht ausschließlich die REST-API des Druckdiensts p12d an,
    lokal mit dem Sitzungs-Token aus session.json, im LAN mit einem API-Token. Sendet immer den
    Kopf X-P12-Source: api, damit der Fehldruckschutz Guard-Rückfragen für diese Quelle vorab
    begrenzt statt sie interaktiv zu stellen.

    Kompatibel zu Windows PowerShell 5.1 und PowerShell 7: kein ternärer Operator, kein
    Null-Coalescing, keine Klassen mit using namespace, Invoke-WebRequest immer
    mit -UseBasicParsing, JSON-Antworten werden selbst als UTF-8 dekodiert.
#>

Set-StrictMode -Version Latest

# ================================================================ Modul-Zustand

$script:P12Uri = $null
$script:P12Token = $null

function ConvertFrom-P12ResponseBytes {
    <#
    .SYNOPSIS
        Dekodiert den Rohkörper einer JSON-Antwort als UTF-8 (nicht exportiert).
    .DESCRIPTION
        Der Druckdienst sendet application/json ohne charset. Windows PowerShell 5.1 liest solche
        Antworten in Invoke-RestMethod und in .Content als ISO-8859-1 (StraÃe statt Straße);
        darum dekodiert der Transport die Rohbytes selbst. Ein UTF-8-BOM wird entfernt, ein leerer
        Körper ergibt $null.
    #>
    [CmdletBinding()]
    param([byte[]]$Bytes)
    if ($null -eq $Bytes -or $Bytes.Length -eq 0) { return $null }
    $text = [System.Text.Encoding]::UTF8.GetString($Bytes).TrimStart([char]0xFEFF)
    if (-not $text.Trim()) { return $null }
    return ($text | ConvertFrom-Json)
}

$script:P12Transport = {
    param($Request)

    $params = @{
        Method         = $Request.Method
        Uri            = $Request.Uri
        Headers        = $Request.Headers
        TimeoutSec     = 60
        UseBasicParsing = $true
    }
    if ($null -ne $Request.Body) {
        $params.Body = $Request.Body
        $params.ContentType = 'application/json; charset=utf-8'
    }
    if ($Request.OutFile) {
        Invoke-WebRequest @params -OutFile $Request.OutFile | Out-Null
        return $null
    }
    # Invoke-WebRequest statt Invoke-RestMethod: nur so kommen die Rohbytes an, die
    # ConvertFrom-P12ResponseBytes selbst als UTF-8 liest (Windows PowerShell 5.1).
    $response = Invoke-WebRequest @params
    $raw = $response.RawContentStream
    if ($null -eq $raw) { return $null }
    if ($raw.CanSeek) { $raw.Position = 0 }
    $buffer = New-Object System.IO.MemoryStream
    try {
        $raw.CopyTo($buffer)
        return ConvertFrom-P12ResponseBytes -Bytes $buffer.ToArray()
    } finally {
        $buffer.Dispose()
    }
}

function Set-P12Transport {
    <#
    .SYNOPSIS
        Ersetzt den HTTP-Transport (nur für Tests, nicht exportiert).
    .DESCRIPTION
        Der übergebene Scriptblock bekommt ein Hashtable @{Method; Uri; Headers; Body; OutFile}
        und liefert das Ergebnis (für Anfragen ohne OutFile) bzw. $null (für Anfragen mit
        OutFile, die die Datei selbst schreiben). Erreichbar per
        & (Get-Module Tapesmith) { Set-P12Transport -ScriptBlock $sb }.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [scriptblock]$ScriptBlock
    )
    $script:P12Transport = $ScriptBlock
}

# ================================================================ Verbindung

function Read-P12Session {
    <#
    .SYNOPSIS
        Liest die Sitzungsdatei der Web-Oberfläche (nicht exportiert).
    .DESCRIPTION
        Pfad <TAPESMITH_HOME oder %APPDATA%\Tapesmith>\web\session.json. TAPESMITH_HOME hat Vorrang
        (alter Name P12LABEL_HOME gilt als Rückfall).
        Liefert $null, wenn die Datei fehlt oder nicht lesbar ist.
    #>
    [CmdletBinding()]
    param()
    $base = $env:TAPESMITH_HOME
    if (-not $base) { $base = $env:P12LABEL_HOME }
    if (-not $base) { $base = Join-Path $env:APPDATA 'Tapesmith' }
    $path = Join-Path $base 'web\session.json'
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    try {
        return Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        return $null
    }
}

function ConvertFrom-P12SecureToken {
    <#
    .SYNOPSIS
        Entschlüsselt einen SecureString zu Klartext (nicht exportiert, nie ausgegeben).
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][System.Security.SecureString]$SecureString)
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    try {
        return [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

function Get-P12Connection {
    <#
    .SYNOPSIS
        Ermittelt Basis-URL und Token für die nächste Anfrage (nicht exportiert).
    .DESCRIPTION
        Reihenfolge: per Connect-P12 gesetzte Modul-Variablen, sonst Umgebungsvariablen
        TAPESMITH_URL/TAPESMITH_TOKEN (Rückfall P12LABEL_URL/P12LABEL_TOKEN), sonst session.json (lokal, http://127.0.0.1:<port>).
    #>
    [CmdletBinding()]
    param()
    if ($script:P12Uri -and $script:P12Token) {
        return @{ Uri = $script:P12Uri; Token = $script:P12Token }
    }
    if ($env:TAPESMITH_URL -and $env:TAPESMITH_TOKEN) {
        return @{ Uri = $env:TAPESMITH_URL.TrimEnd('/'); Token = $env:TAPESMITH_TOKEN }
    }
    # Alte Namen aus der Zeit vor Tapesmith 0.3 (P12 Label) gelten als Rückfall.
    if ($env:P12LABEL_URL -and $env:P12LABEL_TOKEN) {
        return @{ Uri = $env:P12LABEL_URL.TrimEnd('/'); Token = $env:P12LABEL_TOKEN }
    }
    $session = Read-P12Session
    if ($session -and $session.port -and $session.token) {
        return @{ Uri = "http://127.0.0.1:$($session.port)"; Token = $session.token }
    }
    throw 'Druckdienst nicht gefunden: p12 app bzw. p12 daemon start ausführen oder Connect-P12 -Uri ... -Token ... nutzen.'
}

function Connect-P12 {
    <#
    .SYNOPSIS
        Verbindet das Modul mit einem Druckdienst p12d.
    .DESCRIPTION
        Ohne Parameter: lokale Verbindung (http://127.0.0.1:<port>) mit dem Token aus
        session.json (TAPESMITH_HOME hat Vorrang vor %APPDATA%\Tapesmith). Mit -Uri/-Token: LAN-
        oder Testverbindung; -Token als SecureString wird intern entschlüsselt und nie
        ausgegeben.
    .PARAMETER Uri
        Basis-URL des Druckdiensts, z. B. http://192.0.2.50:8712. Ohne Angabe wird die lokale
        Adresse aus session.json verwendet.
    .PARAMETER Token
        API- oder Sitzungs-Token, als SecureString oder Klartext-Zeichenkette. Ohne Angabe wird
        das Token aus session.json verwendet.
    .EXAMPLE
        Connect-P12 -Uri http://192.0.2.50:8712 -Token (Read-Host -AsSecureString)
    #>
    [CmdletBinding()]
    param(
        [string]$Uri,
        [object]$Token
    )
    $session = $null
    if (-not $Uri -or -not $Token) {
        $session = Read-P12Session
    }

    if ($Uri) {
        $script:P12Uri = $Uri.TrimEnd('/')
    } elseif ($session -and $session.port) {
        $script:P12Uri = "http://127.0.0.1:$($session.port)"
    } else {
        throw 'Druckdienst nicht gefunden: p12 app bzw. p12 daemon start ausführen oder Connect-P12 -Uri ... -Token ... nutzen.'
    }

    if ($Token) {
        if ($Token -is [System.Security.SecureString]) {
            $script:P12Token = ConvertFrom-P12SecureToken -SecureString $Token
        } else {
            $script:P12Token = [string]$Token
        }
    } elseif ($session -and $session.token) {
        $script:P12Token = $session.token
    } else {
        throw 'Druckdienst nicht gefunden: p12 app bzw. p12 daemon start ausführen oder Connect-P12 -Uri ... -Token ... nutzen.'
    }
}

function Disconnect-P12 {
    <#
    .SYNOPSIS
        Trennt die Verbindung: nächste Anfrage ermittelt Basis-URL/Token wieder neu.
    #>
    [CmdletBinding()]
    param()
    $script:P12Uri = $null
    $script:P12Token = $null
}

# ================================================================ Transport

function ConvertTo-P12QueryString {
    [CmdletBinding()]
    param([hashtable]$Query)
    if (-not $Query -or $Query.Count -eq 0) { return '' }
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($key in $Query.Keys) {
        $value = $Query[$key]
        if ($null -eq $value) { continue }
        $parts.Add("$([uri]::EscapeDataString($key))=$([uri]::EscapeDataString([string]$value))")
    }
    if ($parts.Count -eq 0) { return '' }
    return '?' + ($parts -join '&')
}

function Invoke-P12Request {
    <#
    .SYNOPSIS
        Führt eine Anfrage an die REST-API des Druckdiensts aus (nicht exportiert).
    .DESCRIPTION
        Einzige interne Funktion, die HTTP spricht (über den austauschbaren Transport
        $script:P12Transport). Setzt Authorization: Bearer <token> und X-P12-Source: api, kodiert
        den JSON-Körper als UTF-8 und wandelt Fehlerantworten im einheitlichen Fehlerformat in einen
        terminierenden Fehler mit message (und hint, sofern vorhanden) um.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [object]$Body,
        [hashtable]$Query,
        [string]$OutFile
    )
    $conn = Get-P12Connection
    $uri = $conn.Uri + $Path + (ConvertTo-P12QueryString -Query $Query)

    $headers = @{
        'Authorization' = "Bearer $($conn.Token)"
        'X-P12-Source'  = 'api'
    }

    $bodyBytes = $null
    if ($null -ne $Body) {
        $json = $Body | ConvertTo-Json -Depth 12 -Compress
        $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    }

    $request = [ordered]@{
        Method  = $Method
        Uri     = $uri
        Headers = $headers
        Body    = $bodyBytes
        OutFile = $OutFile
    }

    try {
        return & $script:P12Transport $request
    } catch {
        $errorBody = $null
        # TargetObject ist bei Invoke-WebRequest die Anfrage (ohne Eigenschaft error): unter
        # Set-StrictMode nur über PSObject.Properties prüfen, sonst PropertyNotFoundException.
        $targetError = $null
        if ($null -ne $_.TargetObject) {
            $targetError = $_.TargetObject.PSObject.Properties['error']
        }
        if ($null -ne $targetError -and $targetError.Value) {
            $errorBody = $targetError.Value
        } elseif ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            try {
                $parsed = $_.ErrorDetails.Message | ConvertFrom-Json
                if ($parsed.error) { $errorBody = $parsed.error }
            } catch {
                $errorBody = $null
            }
        }
        if ($errorBody) {
            $message = [string]$errorBody.message
            if ($errorBody.hint) { $message = "$message ($($errorBody.hint))" }
            throw $message
        }
        throw
    }
}

# ================================================================ Status, Vorlagen

function ConvertTo-P12StatusObject {
    [CmdletBinding()]
    param($Response)
    $report = $Response.report
    $view = $Response.view
    $status = $report.status

    $battery = $null
    $lid = $null
    if ($status -and $status.values) {
        $batteryProp = $status.values.PSObject.Properties['battery']
        if ($batteryProp -and $batteryProp.Value -and $batteryProp.Value.verified) {
            $battery = $batteryProp.Value.value
        }
        $lidProp = $status.values.PSObject.Properties['lid']
        if ($lidProp -and $lidProp.Value -and $lidProp.Value.verified) {
            $lid = $lidProp.Value.value
        }
    }

    [pscustomobject]@{
        Zustand  = $report.state.state
        Text     = $view.chip
        Akku     = $battery
        Deckel   = $lid
        Geprueft = $report.checked_at
    }
}

function Get-P12Status {
    <#
    .SYNOPSIS
        Liest den aktuellen Druckerstatus.
    .DESCRIPTION
        GET /api/v1/status. Nicht verifizierte Werte (Akku, Deckel) kommen als $null zurück.
    .OUTPUTS
        [pscustomobject] mit Zustand, Text, Akku, Deckel, Geprueft.
    .EXAMPLE
        Get-P12Status
    #>
    [CmdletBinding()]
    param()
    $response = Invoke-P12Request -Method 'GET' -Path '/api/v1/status'
    ConvertTo-P12StatusObject -Response $response
}

function ConvertTo-P12TemplateObject {
    [CmdletBinding()]
    param($Template)
    [pscustomobject]@{
        Name         = $Template.name
        Beschreibung = $Template.description
        Kategorie    = $Template.category
        Felder       = $Template.input_fields
    }
}

function Get-P12Template {
    <#
    .SYNOPSIS
        Listet Vorlagen oder liest eine einzelne Vorlage.
    .DESCRIPTION
        Ohne -Name: GET /api/v1/templates (alle Vorlagen). Mit -Name: GET /api/v1/templates/<name>
        (URL-kodiert).
    .PARAMETER Name
        Name der Vorlage. Ohne Angabe werden alle Vorlagen aufgelistet.
    .OUTPUTS
        [pscustomobject] je Vorlage mit Name, Beschreibung, Kategorie, Felder.
    .EXAMPLE
        Get-P12Template
    .EXAMPLE
        Get-P12Template -Name gefriergut
    #>
    [CmdletBinding()]
    param([string]$Name)
    if ($Name) {
        $response = Invoke-P12Request -Method 'GET' -Path "/api/v1/templates/$([uri]::EscapeDataString($Name))"
        ConvertTo-P12TemplateObject -Template $response
    } else {
        $response = Invoke-P12Request -Method 'GET' -Path '/api/v1/templates'
        foreach ($template in $response.templates) {
            ConvertTo-P12TemplateObject -Template $template
        }
    }
}

# ================================================================ Vorschau

function New-P12Preview {
    <#
    .SYNOPSIS
        Erzeugt eine Vorschau als PNG-Datei.
    .DESCRIPTION
        GET /api/v1/preview.png mit Vorlage (und Werten) oder Text.
    .PARAMETER Template
        Name der Vorlage.
    .PARAMETER Values
        Werte für die Vorlagenfelder.
    .PARAMETER Text
        Zeilen für ein Textlabel (ohne Vorlage).
    .PARAMETER OutFile
        Zieldatei für das PNG.
    .PARAMETER Raster
        Rasterbild statt Entwurfsbild anfordern.
    .OUTPUTS
        [System.IO.FileInfo] der geschriebenen Datei.
    .EXAMPLE
        New-P12Preview -Template gefriergut -Values @{inhalt='Suppe'} -OutFile vorschau.png
    #>
    [CmdletBinding(DefaultParameterSetName = 'Template')]
    param(
        [Parameter(Mandatory, ParameterSetName = 'Template')]
        [string]$Template,

        [Parameter(ParameterSetName = 'Template')]
        [hashtable]$Values,

        [Parameter(Mandatory, ParameterSetName = 'Text')]
        [string[]]$Text,

        [Parameter(Mandatory)]
        [string]$OutFile,

        [switch]$Raster
    )
    $query = @{ raster = $(if ($Raster) { '1' } else { '0' }) }
    if ($PSCmdlet.ParameterSetName -eq 'Template') {
        $query.template = $Template
        if ($Values -and $Values.Count -gt 0) {
            $query.values = ($Values | ConvertTo-Json -Depth 6 -Compress)
        }
    } else {
        $query.text = ($Text -join "`n")
    }
    Invoke-P12Request -Method 'GET' -Path '/api/v1/preview.png' -Query $query -OutFile $OutFile | Out-Null
    Get-Item -LiteralPath $OutFile
}

# ================================================================ Drucken

function Send-P12Label {
    <#
    .SYNOPSIS
        Druckt ein Label, auch aus der Pipeline (z. B. Get-PhysicalDisk, Import-Csv).
    .DESCRIPTION
        Parametersatz Template: druckt eine Vorlage mit Werten. Parametersatz Text: druckt reinen
        Text. Über die API gelten höchstens 5 Kopien je Auftrag und Labels bis 150 mm (Guard-
        Rückfrage, Quelle api kann nicht bestätigen); -Confirmed bestätigt nur die Rückfrage,
        dass das eingelegte Band nicht zur Vorlage passt.
    .PARAMETER Template
        Name der Vorlage.
    .PARAMETER Values
        Werte für die Vorlagenfelder (haben Vorrang vor Werten aus -InputObject).
    .PARAMETER Map
        Ordnet Vorlagenfelder Eigenschaften von -InputObject zu, z. B. @{sn='SerialNumber'}. Ohne
        -Map wird jede Eigenschaft verwendet, deren Name (ohne Groß-/Kleinschreibung) einer
        Feld-id der Vorlage entspricht.
    .PARAMETER InputObject
        Objekt aus der Pipeline, dessen Eigenschaften Vorlagenwerte liefern.
    .PARAMETER Text
        Zeilen für ein Textlabel (ohne Vorlage).
    .PARAMETER Copies
        Anzahl Kopien (1 bis 50). Über die API höchstens 5 Kopien je Auftrag (Fehldruckschutz,
        guard.confirm_copies).
    .PARAMETER Confirmed
        Bestätigt nur die Rückfrage, dass das eingelegte Band nicht zur Vorlage passt.
    .OUTPUTS
        [pscustomobject] mit Status, Titel, Warteschlange, Warnungen, Gruende.
    .EXAMPLE
        Send-P12Label -Template gefriergut -Values @{inhalt='Suppe'}
    .EXAMPLE
        Get-PhysicalDisk | Select-Object -First 1 | Send-P12Label -Template datentraeger -Map @{sn='SerialNumber'} -WhatIf
    .EXAMPLE
        Import-Csv kabel.csv | Send-P12Label -Template kabelfahne
    #>
    [CmdletBinding(SupportsShouldProcess, DefaultParameterSetName = 'Template')]
    param(
        [Parameter(Mandatory, ParameterSetName = 'Template')]
        [string]$Template,

        [Parameter(ParameterSetName = 'Template')]
        [hashtable]$Values,

        [Parameter(ParameterSetName = 'Template')]
        [hashtable]$Map,

        [Parameter(ParameterSetName = 'Template', ValueFromPipeline)]
        [psobject]$InputObject,

        [Parameter(Mandatory, ParameterSetName = 'Text')]
        [string[]]$Text,

        [ValidateRange(1, 50)]
        [int]$Copies = 1,

        [switch]$Confirmed
    )
    begin {
        $templateFieldIds = $null
    }
    process {
        $isTemplate = $PSCmdlet.ParameterSetName -eq 'Template'
        # Eigener Name (nicht $values): PowerShell-Variablennamen sind ohne Beachtung der
        # Groß-/Kleinschreibung, $values und der Parameter $Values wären sonst dieselbe
        # Speicherstelle und das Aufzählen von $Values.Keys würde dieselbe Sammlung ändern.
        $fieldValues = @{}

        if ($isTemplate) {
            if ($InputObject) {
                if ($Map -and $Map.Count -gt 0) {
                    foreach ($fieldId in $Map.Keys) {
                        # Über PSObject.Properties prüfen statt per Punktnotation: Unter
                        # Set-StrictMode -Version Latest würde eine fehlende Eigenschaft sonst
                        # eine terminierende PropertyNotFoundException werfen. Fehlt sie, wird
                        # das Feld wie bei $null ausgelassen.
                        $mappedProperty = $InputObject.PSObject.Properties[[string]$Map[$fieldId]]
                        if ($null -ne $mappedProperty -and $null -ne $mappedProperty.Value) {
                            $fieldValues[$fieldId] = [string]$mappedProperty.Value
                        }
                    }
                } else {
                    if ($null -eq $templateFieldIds) {
                        $fields = (Get-P12Template -Name $Template).Felder
                        $templateFieldIds = @($fields | ForEach-Object { $_.id })
                    }
                    foreach ($property in $InputObject.PSObject.Properties) {
                        $fieldId = $templateFieldIds | Where-Object { $_ -ieq $property.Name } | Select-Object -First 1
                        if ($fieldId -and $null -ne $property.Value) {
                            $fieldValues[$fieldId] = [string]$property.Value
                        }
                    }
                }
            }
            if ($Values) {
                foreach ($key in $Values.Keys) { $fieldValues[$key] = [string]$Values[$key] }
            }
            $body = [ordered]@{ template = $Template; values = $fieldValues; copies = $Copies }
            $target = "Vorlage '$Template'"
        } else {
            $body = [ordered]@{ lines = @($Text); copies = $Copies }
            $target = 'Text'
        }
        if ($Confirmed) { $body.confirmed = $true }

        if ($PSCmdlet.ShouldProcess($target, 'Drucken')) {
            $path = $(if ($isTemplate) { '/api/v1/print' } else { '/api/v1/print/text' })
            $response = Invoke-P12Request -Method 'POST' -Path $path -Body $body

            $outcome = [pscustomobject]@{
                Status        = $response.status
                Titel         = $response.title
                Warteschlange = $response.queue_id
                Warnungen     = @($response.warnings)
                Gruende       = @($response.reasons)
            }

            if ($response.status -eq 'bestätigung_nötig') {
                $reasonText = $outcome.Gruende -join ', '
                Write-Warning "Rückfrage nötig: $reasonText. Passt das Band trotzdem, mit -Confirmed erneut senden."
            } elseif ($response.status -eq 'abgelehnt') {
                $reasonText = $outcome.Gruende -join ', '
                Write-Error "Abgelehnt: $reasonText. Über die API gelten höchstens 5 Kopien je Auftrag und Labels bis 150 mm."
            }
            Write-Output $outcome
        } else {
            $previewFile = Join-Path $env:TEMP "p12-vorschau-$(Get-Random -Maximum 999999).png"
            if ($isTemplate) {
                New-P12Preview -Template $Template -Values $fieldValues -OutFile $previewFile | Out-Null
            } else {
                New-P12Preview -Text $Text -OutFile $previewFile | Out-Null
            }
            Write-Output $previewFile
        }
    }
}

# ================================================================ Warteschlange

function Get-P12Job {
    <#
    .SYNOPSIS
        Listet die Aufträge der Warteschlange.
    .PARAMETER IncludeDone
        Auch erledigte Aufträge einbeziehen.
    .OUTPUTS
        [pscustomobject] je Auftrag mit Id, Zustand, Titel, Quelle, Erstellt, Fehler.
    .EXAMPLE
        Get-P12Job -IncludeDone
    #>
    [CmdletBinding()]
    param([switch]$IncludeDone)
    $query = @{ include_done = $(if ($IncludeDone) { 'true' } else { 'false' }) }
    $response = Invoke-P12Request -Method 'GET' -Path '/api/v1/jobs' -Query $query
    foreach ($job in $response.jobs) {
        [pscustomobject]@{
            Id       = $job.id
            Zustand  = $job.state
            Titel    = $job.title
            Quelle   = $job.source
            Erstellt = $job.created
            Fehler   = $job.last_error
        }
    }
}

function Remove-P12Job {
    <#
    .SYNOPSIS
        Entfernt einen Auftrag aus der Warteschlange.
    .PARAMETER Id
        Id des Auftrags (auch per Pipeline-Eigenschaft).
    .EXAMPLE
        Get-P12Job | Where-Object Zustand -eq wartet | Remove-P12Job
    #>
    [CmdletBinding(SupportsShouldProcess)]
    param(
        [Parameter(Mandatory, ValueFromPipelineByPropertyName)]
        [int]$Id
    )
    process {
        if ($PSCmdlet.ShouldProcess("Auftrag $Id", 'Löschen')) {
            $response = Invoke-P12Request -Method 'DELETE' -Path "/api/v1/jobs/$Id"
            [pscustomobject]@{ Id = $Id; Ok = [bool]$response.ok }
        }
    }
}

Export-ModuleMember -Function @(
    'Connect-P12',
    'Disconnect-P12',
    'Get-P12Status',
    'Get-P12Template',
    'Send-P12Label',
    'New-P12Preview',
    'Get-P12Job',
    'Remove-P12Job'
)
