param(
    [Parameter(Mandatory = $true)]
    [string]$Sql,

    [hashtable]$Params = @{},

    [int]$MaxRows = 500,

    [string]$BaseUrl = $env:MDTAS_API_BASE_URL,

    [string]$WriteToken = $env:MDTAS_API_WRITE_TOKEN
)

function Invoke-MdtasSqlApi {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Statement,

        [hashtable]$StatementParams = @{},

        [int]$StatementMaxRows = 500,

        [Parameter(Mandatory = $true)]
        [string]$ApiBaseUrl,

        [Parameter(Mandatory = $true)]
        [string]$ApiWriteToken
    )

    if (-not $ApiBaseUrl) {
        throw "Missing API base URL. Set MDTAS_API_BASE_URL or pass -BaseUrl."
    }
    if (-not $ApiWriteToken) {
        throw "Missing write token. Set MDTAS_API_WRITE_TOKEN or pass -WriteToken."
    }

    $url = "$($ApiBaseUrl.TrimEnd('/'))/admin/sql/execute"
    $body = @{
        sql = $Statement
        params = $StatementParams
        max_rows = $StatementMaxRows
    } | ConvertTo-Json -Depth 6

    Invoke-RestMethod -Method Post -Uri $url -Headers @{ "X-API-Key" = $ApiWriteToken } -ContentType "application/json" -Body $body
}

$result = Invoke-MdtasSqlApi -Statement $Sql -StatementParams $Params -StatementMaxRows $MaxRows -ApiBaseUrl $BaseUrl -ApiWriteToken $WriteToken
$result | ConvertTo-Json -Depth 8
