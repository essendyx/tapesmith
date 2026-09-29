#Requires -Version 5.1
<#
    Testskript für das Modul Tapesmith, ohne Pester. Aufruf:
        powershell -NoProfile -ExecutionPolicy Bypass -File tests\ps\Tapesmith.Tests.ps1
    Ersetzt den HTTP-Transport durch einen Fake (Set-P12Transport), der jede Anfrage aufzeichnet
    und feste Antworten liefert. Schreibt am Ende genau eine JSON-Zeile auf stdout:
        {"ok": bool, "failures": [...], "requests": [{method, uri, headers, body}, ...]}
    Öffnet nie einen echten Port und spricht nie einen echten Dienst an.
#>

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ================================================================ Hilfsfunktionen

$script:Failures = New-Object System.Collections.Generic.List[string]
$script:Requests = New-Object System.Collections.Generic.List[object]
$script:UseStatusOhneAkku = $false

function Add-P12Failure {
    param([string]$Message)
    $script:Failures.Add($Message) | Out-Null
}

function Assert-Equal {
    param($Actual, $Expected, [string]$Message)
    $ok = $false
    if ($null -eq $Actual -and $null -eq $Expected) {
        $ok = $true
    } elseif ($null -ne $Actual -and $Actual -eq $Expected) {
        $ok = $true
    }
    if (-not $ok) {
        Add-P12Failure "$Message : erwartet '$Expected', erhalten '$Actual'"
    }
}

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { Add-P12Failure $Message }
}

function Assert-Match {
    param([string]$Actual, [string]$Pattern, [string]$Message)
    if ($null -eq $Actual -or $Actual -notmatch [regex]::Escape($Pattern)) {
        Add-P12Failure "$Message : '$Pattern' nicht gefunden in '$Actual'"
    }
}

function Test-P12JsonEqual {
    param($A, $B)
    if ($null -eq $A -and $null -eq $B) { return $true }
    if ($null -eq $A -or $null -eq $B) { return $false }
    $aIsList = ($A -is [System.Collections.IEnumerable]) -and ($A -isnot [string])
    $bIsList = ($B -is [System.Collections.IEnumerable]) -and ($B -isnot [string])
    if ($aIsList -and $bIsList) {
        $aArr = @($A)
        $bArr = @($B)
        if ($aArr.Count -ne $bArr.Count) { return $false }
        for ($i = 0; $i -lt $aArr.Count; $i++) {
            if (-not (Test-P12JsonEqual $aArr[$i] $bArr[$i])) { return $false }
        }
        return $true
    }
    if ($A -is [System.Management.Automation.PSCustomObject] -and $B -is [System.Management.Automation.PSCustomObject]) {
        # Unter Set-StrictMode wirft das Herausgreifen von .Name aus einer leeren
        # PSObject.Properties-Sammlung PropertyNotFoundStrict; darum per ForEach-Object.
        $aNames = @($A.PSObject.Properties | ForEach-Object { $_.Name } | Sort-Object)
        $bNames = @($B.PSObject.Properties | ForEach-Object { $_.Name } | Sort-Object)
        if (($aNames -join ',') -ne ($bNames -join ',')) { return $false }
        foreach ($name in $aNames) {
            if (-not (Test-P12JsonEqual $A.$name $B.$name)) { return $false }
        }
        return $true
    }
    return ($A -eq $B)
}

function Assert-JsonEqual {
    param([string]$ActualJson, [string]$ExpectedJson, [string]$Message)
    if (-not $ActualJson) {
        Add-P12Failure "$Message : kein Anfragekoerper vorhanden"
        return
    }
    $a = $ActualJson | ConvertFrom-Json
    $b = $ExpectedJson | ConvertFrom-Json
    if (-not (Test-P12JsonEqual $a $b)) {
        Add-P12Failure "$Message : erwartet $ExpectedJson, erhalten $ActualJson"
    }
}

function Get-LastRequest {
    param([int]$Offset = 0)
    $index = $script:Requests.Count - 1 - $Offset
    if ($index -lt 0) { return $null }
    return $script:Requests[$index]
}

# ================================================================ Testumgebung

$testHome = Join-Path $env:TEMP "tapesmith-pstests-$([guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path (Join-Path $testHome 'web') -Force | Out-Null
$env:TAPESMITH_HOME = $testHome
$env:TAPESMITH_URL = $null
$env:TAPESMITH_TOKEN = $null

$sessionPath = Join-Path $testHome 'web\session.json'
(@{ port = 8712; token = 'sess' } | ConvertTo-Json -Compress) |
    Set-Content -LiteralPath $sessionPath -Encoding UTF8

$modulePath = Join-Path $PSScriptRoot '..\..\deploy\powershell\Tapesmith\Tapesmith.psd1'
Import-Module $modulePath -Force

# ================================================================ Fake-Antworten

$script:FakeStatus = [pscustomobject]@{
    report = [pscustomobject]@{
        state      = [pscustomobject]@{ state = 'verbunden' }
        status     = [pscustomobject]@{
            values = [pscustomobject]@{
                battery = [pscustomobject]@{ value = 75; verified = $true }
                lid     = [pscustomobject]@{ value = 'zu'; verified = $true }
            }
        }
        checked_at = '2026-09-28T10:00:00'
    }
    view   = [pscustomobject]@{ chip = 'Tapesmith: verbunden' }
}

$script:FakeStatusOhneAkku = [pscustomobject]@{
    report = [pscustomobject]@{
        state      = [pscustomobject]@{ state = 'verbunden' }
        status     = [pscustomobject]@{
            values = [pscustomobject]@{
                lid = [pscustomobject]@{ value = 'zu'; verified = $true }
            }
        }
        checked_at = '2026-09-28T10:05:00'
    }
    view   = [pscustomobject]@{ chip = 'Tapesmith: verbunden' }
}

$script:FakeTemplateGefriergut = [pscustomobject]@{
    name         = 'gefriergut'
    description  = 'Gefriergut-Etikett'
    category     = 'kueche'
    input_fields = @(
        [pscustomobject]@{ id = 'inhalt'; label = 'Inhalt'; type = 'text' }
    )
}

$script:FakeJobsResponse = [pscustomobject]@{
    jobs = @(
        [pscustomobject]@{
            id         = 3
            state      = 'wartet'
            title      = 'Test'
            source     = 'api'
            created    = '2026-09-28T10:00:00'
            last_error = $null
        }
    )
}

# ================================================================ Fake-Transport

$FakeTransport = {
    param($Request)

    $bodyText = $null
    if ($null -ne $Request.Body) {
        $bodyText = [System.Text.Encoding]::UTF8.GetString($Request.Body)
    }
    $script:Requests.Add([pscustomobject]@{
        Method  = $Request.Method
        Uri     = $Request.Uri
        Headers = $Request.Headers
        Body    = $bodyText
        OutFile = $Request.OutFile
    })

    $bodyObj = $null
    if ($bodyText) {
        try { $bodyObj = $bodyText | ConvertFrom-Json } catch { $bodyObj = $null }
    }

    $uriPath = ([uri]$Request.Uri).AbsolutePath

    if ($Request.Method -eq 'GET' -and $uriPath -eq '/api/v1/status') {
        if ($script:UseStatusOhneAkku) { return $script:FakeStatusOhneAkku }
        return $script:FakeStatus
    }
    if ($Request.Method -eq 'GET' -and $uriPath -eq '/api/v1/templates/gefriergut') {
        return $script:FakeTemplateGefriergut
    }
    if ($Request.Method -eq 'GET' -and $uriPath -eq '/api/v1/preview.png') {
        if ($Request.OutFile) {
            [System.IO.File]::WriteAllBytes($Request.OutFile, [byte[]](0x89, 0x50, 0x4E, 0x47))
        }
        return $null
    }
    if ($Request.Method -eq 'POST' -and $uriPath -eq '/api/v1/print') {
        if ($bodyObj -and $bodyObj.template -eq 'kaputt') {
            $errorJson = '{"error":{"kind":"NotFound","message":"Vorlage ''kaputt'' unbekannt",' +
                '"hint":"Verfügbare Vorlagen mit Get-P12Template anzeigen","exit_code":6,"details":null}}'
            $exception = New-Object System.Exception('Fehlerantwort')
            $errorRecord = New-Object System.Management.Automation.ErrorRecord(
                $exception, 'P12FakeError', [System.Management.Automation.ErrorCategory]::InvalidOperation, $null)
            $errorRecord.ErrorDetails = New-Object System.Management.Automation.ErrorDetails($errorJson)
            throw $errorRecord
        }
        if ($bodyObj -and [int]$bodyObj.copies -eq 6) {
            return [pscustomobject]@{
                status   = 'abgelehnt'
                title    = $bodyObj.template
                queue_id = $null
                warnings = @()
                reasons  = @('6 Kopien', 'Quelle api kann nicht bestätigen')
            }
        }
        return [pscustomobject]@{
            status   = 'ok'
            title    = $bodyObj.template
            queue_id = 1
            warnings = @()
            reasons  = @()
        }
    }
    if ($Request.Method -eq 'POST' -and $uriPath -eq '/api/v1/print/text') {
        return [pscustomobject]@{
            status   = 'ok'
            title    = 'Text'
            queue_id = 2
            warnings = @()
            reasons  = @()
        }
    }
    if ($Request.Method -eq 'GET' -and $uriPath -eq '/api/v1/jobs') {
        return $script:FakeJobsResponse
    }
    if ($Request.Method -eq 'DELETE' -and $uriPath -eq '/api/v1/jobs/3') {
        return [pscustomobject]@{ ok = $true }
    }

    throw "Unerwartete Testanfrage: $($Request.Method) $uriPath"
}

$p12Module = Get-Module Tapesmith

# ================================================================ Test 0: echter Transport dekodiert UTF-8
# Regression: Windows PowerShell 5.1 dekodiert JSON-Antworten ohne charset als ISO-8859-1
# (StraÃŸe statt Straße). Der echte Transport muss die Rohbytes selbst als UTF-8 lesen. Ohne
# Netzwerk: Invoke-WebRequest und Invoke-RestMethod werden im Modulbereich durch Funktionen
# ersetzt, die feste UTF-8-Bytes liefern (bzw. einen Fehler werfen).
$utf8Json = '{"name":"Straße · grün","message":"Kontingent für api erschöpft"}'
$utf8Bytes = [System.Text.Encoding]::UTF8.GetBytes($utf8Json)
$decodeResult = $null
try {
    $decodeResult = & $p12Module {
        param($Bytes)
        function script:Invoke-WebRequest {
            $latin1 = [System.Text.Encoding]::GetEncoding(28591).GetString($Bytes)
            [pscustomobject]@{
                StatusCode       = 200
                Content          = $latin1
                RawContentStream = (New-Object System.IO.MemoryStream -ArgumentList (,[byte[]]$Bytes))
            }
        }
        function script:Invoke-RestMethod { throw 'Invoke-RestMethod darf der Transport nicht nutzen' }
        try {
            $request = [ordered]@{
                Method  = 'GET'
                Uri     = 'http://127.0.0.1:8712/api/v1/templates'
                Headers = @{}
                Body    = $null
                OutFile = $null
            }
            & $script:P12Transport $request
        } finally {
            Remove-Item -Path function:script:Invoke-WebRequest -ErrorAction SilentlyContinue
            Remove-Item -Path function:script:Invoke-RestMethod -ErrorAction SilentlyContinue
        }
    } $utf8Bytes
} catch {
    Add-P12Failure "Test0 echter Transport: $($_.Exception.Message)"
}
if ($null -ne $decodeResult) {
    Assert-Equal $decodeResult.name 'Straße · grün' 'Test0 Umlaute aus dem echten Transport'
    Assert-Equal $decodeResult.message 'Kontingent für api erschöpft' 'Test0 Meldung aus dem echten Transport'
} else {
    Add-P12Failure 'Test0 echter Transport lieferte kein Ergebnis'
}

# Fehlerantwort über den echten Transport: Das ErrorRecord von Invoke-WebRequest trägt als
# TargetObject die Anfrage (ohne Eigenschaft error). Unter Set-StrictMode darf das nicht mit
# PropertyNotFoundException enden, die Meldung aus ErrorDetails muss ankommen.
$errorCaught = $null
& $p12Module {
    function script:Invoke-WebRequest {
        $errorJson = '{"error":{"message":"Kontingent für api erschöpft","hint":"Straße"}}'
        $exception = New-Object System.Exception('Der Remoteserver hat einen Fehler zurückgegeben: (429)')
        $errorRecord = New-Object System.Management.Automation.ErrorRecord(
            $exception, 'WebCmdletWebResponseException', [System.Management.Automation.ErrorCategory]::InvalidOperation,
            ([System.Uri]'http://127.0.0.1:8712/api/v1/status'))
        $errorRecord.ErrorDetails = New-Object System.Management.Automation.ErrorDetails($errorJson)
        throw $errorRecord
    }
}
try {
    Get-P12Status | Out-Null
} catch {
    $errorCaught = $_.Exception.Message
} finally {
    & $p12Module { Remove-Item -Path function:script:Invoke-WebRequest -ErrorAction SilentlyContinue }
}
Assert-Equal $errorCaught 'Kontingent für api erschöpft (Straße)' 'Test0 Fehlermeldung aus dem echten Transport'

& $p12Module { Set-P12Transport -ScriptBlock $args[0] } $FakeTransport

# ================================================================ Test 1: ohne Connect-P12

Get-P12Status | Out-Null
$req = Get-LastRequest
Assert-Equal $req.Uri 'http://127.0.0.1:8712/api/v1/status' 'Test1 Uri'
Assert-Equal $req.Headers['Authorization'] 'Bearer sess' 'Test1 Authorization'
Assert-Equal $req.Headers['X-P12-Source'] 'api' 'Test1 X-P12-Source'

# ================================================================ Test 2: Connect-P12 / Disconnect-P12

Connect-P12 -Uri 'http://192.0.2.50:8712' -Token 'p12_x'
Get-P12Status | Out-Null
$req = Get-LastRequest
Assert-Equal $req.Uri 'http://192.0.2.50:8712/api/v1/status' 'Test2 Uri nach Connect-P12'
Assert-Equal $req.Headers['Authorization'] 'Bearer p12_x' 'Test2 Authorization nach Connect-P12'

Disconnect-P12
Get-P12Status | Out-Null
$req = Get-LastRequest
Assert-Equal $req.Uri 'http://127.0.0.1:8712/api/v1/status' 'Test2 Uri nach Disconnect-P12'
Assert-Equal $req.Headers['Authorization'] 'Bearer sess' 'Test2 Authorization nach Disconnect-P12'

# ================================================================ Test 3: Send-P12Label -Template

$outcome = Send-P12Label -Template gefriergut -Values @{ inhalt = 'Suppe' }
$req = Get-LastRequest
Assert-Equal $req.Method 'POST' 'Test3 Methode'
Assert-Equal $req.Uri 'http://127.0.0.1:8712/api/v1/print' 'Test3 Uri'
Assert-JsonEqual $req.Body '{"template":"gefriergut","values":{"inhalt":"Suppe"},"copies":1}' 'Test3 Koerper'
Assert-Equal $outcome.Status 'ok' 'Test3 Status'

# ================================================================ Test 4: Pipeline mit -Map

$before = $script:Requests.Count
[pscustomobject]@{ SerialNumber = 'A1' }, [pscustomobject]@{ SerialNumber = 'B2' } |
    Send-P12Label -Template datentraeger -Map @{ sn = 'SerialNumber' } | Out-Null
Assert-Equal ($script:Requests.Count - $before) 2 'Test4 Anzahl Anfragen'
$reqA = Get-LastRequest -Offset 1
$reqB = Get-LastRequest -Offset 0
Assert-JsonEqual $reqA.Body '{"template":"datentraeger","values":{"sn":"A1"},"copies":1}' 'Test4 Koerper A1'
Assert-JsonEqual $reqB.Body '{"template":"datentraeger","values":{"sn":"B2"},"copies":1}' 'Test4 Koerper B2'

# ================================================================ Test 5: automatische Zuordnung

$before = $script:Requests.Count
[pscustomobject]@{ Inhalt = 'Marmelade' } | Send-P12Label -Template gefriergut | Out-Null
Assert-Equal ($script:Requests.Count - $before) 2 'Test5 Anzahl Anfragen (Vorlage abrufen + drucken)'
$templateReq = Get-LastRequest -Offset 1
$printReq = Get-LastRequest -Offset 0
Assert-Equal $templateReq.Uri 'http://127.0.0.1:8712/api/v1/templates/gefriergut' 'Test5 Uri Vorlagenabruf'
Assert-JsonEqual $printReq.Body '{"template":"gefriergut","values":{"inhalt":"Marmelade"},"copies":1}' 'Test5 Koerper'

# ================================================================ Test 6: -WhatIf

$before = $script:Requests.Count
$previewPath = Send-P12Label -Template gefriergut -Values @{ inhalt = 'Suppe' } -WhatIf
Assert-Equal ($script:Requests.Count - $before) 1 'Test6 Anzahl Anfragen'
$req = Get-LastRequest
Assert-Equal $req.Method 'GET' 'Test6 Methode'
Assert-True ($req.Uri -like '*preview.png*') 'Test6 Vorschau-Endpunkt'
Assert-True ([bool]$req.OutFile) 'Test6 OutFile gesetzt'
Assert-True (Test-Path -LiteralPath $previewPath) 'Test6 Vorschaudatei existiert'

# ================================================================ Test 7: Send-P12Label -Text

$outcomeText = Send-P12Label -Text 'A', 'B'
$req = Get-LastRequest
Assert-Equal $req.Uri 'http://127.0.0.1:8712/api/v1/print/text' 'Test7 Uri'
Assert-JsonEqual $req.Body '{"lines":["A","B"],"copies":1}' 'Test7 Koerper'
Assert-Equal $outcomeText.Status 'ok' 'Test7 Status'

# ================================================================ Test 8: abgelehnt (6 Kopien)

$ev = $null
$outcomeRejected = Send-P12Label -Template gefriergut -Values @{ inhalt = 'Suppe' } -Copies 6 `
    -ErrorVariable ev -ErrorAction SilentlyContinue
Assert-Equal $outcomeRejected.Status 'abgelehnt' 'Test8 Status'
$evText = ($ev | ForEach-Object { $_.ToString() }) -join ' | '
Assert-Match $evText 'Abgelehnt:' 'Test8 Fehlertext Abgelehnt'
Assert-Match $evText 'höchstens 5 Kopien' 'Test8 Fehlertext Grenze'

# ================================================================ Test 9: Copies 51 (Parameterprüfung)

$before = $script:Requests.Count
$caught = $null
try {
    Send-P12Label -Text 'A' -Copies 51 | Out-Null
} catch {
    $caught = $_
}
Assert-True ($null -ne $caught) 'Test9 Fehler bei ungueltiger Kopienzahl'
Assert-Equal $script:Requests.Count $before 'Test9 keine Anfrage gesendet'

# ================================================================ Test 10: -Confirmed

$outcomeConfirmed = Send-P12Label -Template gefriergut -Values @{ inhalt = 'Suppe' } -Confirmed
$req = Get-LastRequest
Assert-JsonEqual $req.Body '{"template":"gefriergut","values":{"inhalt":"Suppe"},"copies":1,"confirmed":true}' 'Test10 Koerper'

# ================================================================ Test 11: Fehlerantwort (422)

$caught = $null
try {
    Send-P12Label -Template kaputt -Values @{} | Out-Null
} catch {
    $caught = $_
}
Assert-True ($null -ne $caught) 'Test11 terminierender Fehler'
if ($null -ne $caught) {
    Assert-Match $caught.Exception.Message "Vorlage 'kaputt' unbekannt" 'Test11 Fehlermeldung'
    Assert-Match $caught.Exception.Message 'Verfügbare Vorlagen mit Get-P12Template anzeigen' 'Test11 Fehlerhinweis'
}

# ================================================================ Test 12: Get-P12Job / Remove-P12Job

$jobs = @(Get-P12Job)
Assert-Equal $jobs.Count 1 'Test12 Anzahl Auftraege'
Assert-Equal $jobs[0].Id 3 'Test12 Id'
Assert-Equal $jobs[0].Zustand 'wartet' 'Test12 Zustand'

$removed = Remove-P12Job -Id 3 -Confirm:$false
$req = Get-LastRequest
Assert-Equal $req.Method 'DELETE' 'Test12 DELETE-Methode'
Assert-Equal $req.Uri 'http://127.0.0.1:8712/api/v1/jobs/3' 'Test12 DELETE-Uri'
Assert-Equal $removed.Ok $true 'Test12 Ok'

# ================================================================ Test 13: Umlaute UTF-8

Send-P12Label -Text 'Gewürze' | Out-Null
$req = Get-LastRequest
Assert-True ($req.Body -like '*Gewürze*') 'Test13 Umlaute im Koerper'

# ================================================================ Test 14: Get-P12Status Feldnamen (ASCII: Akku, Deckel, Geprueft)

$status = Get-P12Status
Assert-Equal $status.Zustand 'verbunden' 'Test14 Zustand'
Assert-Equal $status.Akku 75 'Test14 Akku'
Assert-Equal $status.Deckel 'zu' 'Test14 Deckel'
Assert-Equal $status.Geprueft '2026-09-28T10:00:00' 'Test14 Geprueft'

# ================================================================ Test 15: Get-P12Status ohne battery-Schluessel
# Regression: status.values kann battery/lid komplett auslassen, solange der Wert nicht
# verifiziert ist. Set-StrictMode -Version Latest darf dabei NICHT mit PropertyNotFoundException
# abstuerzen; Akku muss $null werden statt eines Fehlers.

$script:UseStatusOhneAkku = $true
$caught = $null
$statusOhneAkku = $null
try {
    $statusOhneAkku = Get-P12Status
} catch {
    $caught = $_
}
$script:UseStatusOhneAkku = $false
Assert-True ($null -eq $caught) 'Test15 kein Absturz ohne battery-Schluessel'
if ($null -ne $caught) {
    Add-P12Failure "Test15 Ausnahme: $($caught.Exception.Message)"
} else {
    Assert-Equal $statusOhneAkku.Akku $null 'Test15 Akku null ohne battery-Schluessel'
    Assert-Equal $statusOhneAkku.Deckel 'zu' 'Test15 Deckel bleibt gesetzt'
}

# ================================================================ Test 16: Send-P12Label Feldname Gruende (ASCII)

Assert-Equal $outcomeRejected.Gruende.Count 2 'Test16 Gruende Anzahl'
Assert-Match ($outcomeRejected.Gruende -join ', ') '6 Kopien' 'Test16 Gruende Inhalt'

# ================================================================ Test 17: -Map mit fehlender Eigenschaft
# Regression: Ein Pipeline-Objekt ohne die gemappte Eigenschaft (Tippfehler im Map-Wert,
# uneinheitliche CSV-Spalten) darf unter Set-StrictMode -Version Latest nicht mit
# PropertyNotFoundException abstuerzen. Das Feld wird ausgelassen, wie bei $null.

$before = $script:Requests.Count
$caught = $null
try {
    [pscustomobject]@{ SerialNumber = 'C3' }, [pscustomobject]@{ Anderes = 'x' } |
        Send-P12Label -Template datentraeger -Map @{ sn = 'SerialNumber' } | Out-Null
} catch {
    $caught = $_
}
Assert-True ($null -eq $caught) 'Test17 kein Absturz bei fehlender Map-Eigenschaft'
if ($null -ne $caught) {
    Add-P12Failure "Test17 Ausnahme: $($caught.Exception.Message)"
} else {
    Assert-Equal ($script:Requests.Count - $before) 2 'Test17 Anzahl Anfragen'
    Assert-JsonEqual (Get-LastRequest -Offset 1).Body '{"template":"datentraeger","values":{"sn":"C3"},"copies":1}' 'Test17 Koerper C3'
    Assert-JsonEqual (Get-LastRequest -Offset 0).Body '{"template":"datentraeger","values":{},"copies":1}' 'Test17 Koerper ohne Eigenschaft'
}

# Auch im Vorschau-Modus (-WhatIf) kein Absturz.
$caught = $null
try {
    [pscustomobject]@{ Anderes = 'x' } |
        Send-P12Label -Template datentraeger -Map @{ sn = 'SerialNumbr' } -WhatIf | Out-Null
} catch {
    $caught = $_
}
Assert-True ($null -eq $caught) 'Test17 kein Absturz bei -WhatIf mit Tippfehler im Map-Wert'
if ($null -ne $caught) { Add-P12Failure "Test17 WhatIf-Ausnahme: $($caught.Exception.Message)" }

# ================================================================ Ergebnis

$ok = ($script:Failures.Count -eq 0)
$result = [pscustomobject]@{
    ok       = $ok
    failures = @($script:Failures)
    requests = @($script:Requests | ForEach-Object {
        [pscustomobject]@{
            method  = $_.Method
            uri     = $_.Uri
            headers = $_.Headers
            body    = $_.Body
        }
    })
}
Write-Output ($result | ConvertTo-Json -Depth 10 -Compress)

if (-not $ok) { exit 1 }
exit 0
