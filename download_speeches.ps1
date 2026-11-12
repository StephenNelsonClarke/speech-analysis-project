$base = "https://www.bankofengland.co.uk/speech/"
$outputRoot = $PSScriptRoot

$speechSlugs = @(
    # Relative speech paths or complete speech/PDF URLs

"2022/june/catherine-l-mann-speech-at-a-market-news-international-connect-event",
"2022/june/huw-pill-speech-at-the-walter-eucken-institute",

"2022/july/huw-pill-keynote-address-at-the-qatar-centre-for-global-banking-and-finance-2022-conference",
"2022/july/huw-pill-speech-at-the-sheffield-hallam-university",
"2022/july/jon-cunliffe-speech-on-crypto-market-developments-at-the-british-high-commission-singapore",
"2022/july/andrew-bailey-speech-at-omfif-the-economic-landscape",
"2022/july/michael-saunders-speech-at-the-resolution-foundation",
"2022/july/andrew-bailey-speech-at-mansion-house-financial-and-professional-services-dinner",

"2022/september/catherine-l-mann-53rd-annual-conference-of-the-money-macro-and-finance-society",
"2022/september/jon-cunliffe-keynote-speech-at-the-afme-operations-post-trade-technology-innovation-conference",
"2022/september/dave-ramsden-panellist-at-the-joint-conference-with-the-bank-of-lithuania",
"2022/september/huw-pill-speech-at-the-institute-of-directors-dinner",

"2022/october/current-monetary-policy-opening-remarks-by-jonathan-haskel",
"2022/october/dave-ramsden-speech-at-the-securities-industry-conference",
"2022/october/huw-pill-in-conversation-with-scdi",
"2022/october/andrew-bailey-opening-remarks-and-panellist-37th-annual-international-banking-seminar",
"2022/october/ben-broadbent-speech-at-imperial-college-the-inflationary-consequences-of-real-shocks",

"2022/november/silvana-tenreyro-keynote-speech-at-the-society-of-professional-economists-annual-conference",
"2022/november/jonathan-haskel-seminar-at-bank-of-israel",
"2022/november/challenge-convene-collaborate-and-create-speech-by-sir-dave-ramsden",
"2022/november/jon-cunliffe-keynote-speech-and-panel-at-warwick-conference-on-defi-digital-currencies",
"2022/november/huw-pill-speech-at-the-beesley-lecture-series",
"2022/november/dave-ramsden-keynote-speech-at-boe-watchers-conference",

"2023/january/huw-pill-chair-and-general-discussant-at-the-american-economics-association-annual-meeting",
"2023/february/catherine-l-mann-lamfalussy-lectures-conference-new-dimensions-of-central-baking-post-covid",
"2023/february/huw-pill-fireside-chat-at-the-warwick-think-tank-on-the-uk-economy",
"2023/february/catherine-l-mann-speech-resolution-foundation",
"2023/february/silvana-tenreyro-conference-frb-of-ny-panellist-at-the-session-back-to-2-inflation",

"2023/march/andrew-bailey-speech-at-london-school-of-economics",
"2023/march/sarah-breeden-speech-on-macro-prudential-monetary-policy-interactions-at-leeds-university",
"2023/march/swati-dhingra-remarks-on-cost-of-living-crisis-and-inflation-at-the-resolution-foundation",
"2023/march/andrew-bailey-speech-at-cost-of-living-crisis-conference-brunswick-group",

"2023/april/ben-broadbent-speech-hosted-by-national-institute-of-economic-and-social-research",
"2023/april/andrew-bailey-remarks-at-the-institute-of-international-finance",
"2023/april/huw-pill-speech-at-the-international-centre-for-monetary-and-banking-studies-public-lecture",
"2023/april/quantitative-easing-quantitative-tightening-speech-silvana-tenreyro",

"2023/may/jonathan-haskel-speech-at-peterson-institute-for-international-economics",
"2023/may/andrew-bailey-keynote-speech-british-chambers-of-commerce-global-annual-conference",

"2023/june/silvana-tenreyro-speech-at-the-society-of-professional-economists",

"2023/july/dave-ramsden-speech-on-quantitative-tightening-chaired-by-money-macro-and-finance-society",
"2023/july/andrew-bailey-speech-at-the-financial-and-professional-services-dinner",

"2023/august/huw-pill-speaker-at-the-south-african-reserve-bank-biennial-conference-back-to-target",

"2023/september/catherine-l-mann-speech-canadian-association-for-business-economics-conference",

"2023/november/dave-ramsden-remarks-at-the-7th-annual-conference-of-the-european-systemic-risk-board",
"2023/november/catherine-l-mann-university-of-oxford-environmental-economics-seminar",
"2023/november/jonathan-haskel-panellist-at-the-boe-watchers-conference-labour-market-dynamics",
"2023/november/andrew-bailey-remarks-at-the-50-year-anniversary-of-the-london-fxjsc",
"2023/november/megan-greene-speech-at-leeds-university",

"2023/december/dave-ramsden-speech-at-deloitte-academy-on-the-banks-resolution-regime",
"2023/december/ben-broadbent-speech-at-london-business-school",

"2023/december/sarah-breeden-speech-at-the-iff-talking-policy-series",

"2024/february/sarah-breeden-keynote-speech-uk-women-in-economics-annual-networking",
"2024/february/swati-dhingra-market-news-international-connect-event",
"2024/february/megan-greene-fireside-chat-with-brian-coulton-chief-economist-fitch-ratings",
"2024/february/andrew-bailey-lecture-at-loughborough-university",
"2024/february/catherine-l-mann-speech-at-the-official-monetary-and-financial-institution",

"2024/march/huw-pill-speech-at-the-cardiff-university-business-school",

"2024/april/huw-pill-speech-at-univeristy-of-chicago-booth-business-school",
"2024/april/dave-ramsden-pannellist-at-peterson-institute-for-international-economics-conference",
"2024/april/sarah-breeden-keynote-speech-at-the-innovate-finance-global-summit-2024",

"2024/may/remarks-given-by-swati-dhingra-at-econdat-2024",
"2024/may/andrew-bailey-lecture-london-school-of-economics-charles-goodhart",
"2024/may/ben-broadbent-ccbs-new-evidence-on-the-monetary-transmission-mechanism-workshop",
"2024/may/catherine-l-mann-cost-of-capital-and-uk-business-investment-slides",
"2024/may/megan-greene-speech-at-make-uk-the-current-state-of-britains-labour-market",

"2024/july/huw-pill-speech-at-asia-house",

"2024/august/andrew-bailey-speech-federal-reserve-bank-of-kansas-annual-jackson-hole-economic-policy-symposium",

"2024/september/catherine-l-mann-keynote-speech-at-the-central-bank-research-association",
"2024/september/sarah-breeden-remarks-from-the-wharton-imf-transatlantic-dialogue",
"2024/september/megan-greene-speech-on-consumption-hosted-by-the-chambers-of-commerce-newcastle",

"2024/october/sarah-breeden-keynote-speech-at-the-hong-kong-monetary-authority",
"2024/october/swati-dhingra-panellist-at-the-reserve-bank-of-india-conference",
"2024/october/huw-pill-speech-at-the-institute-chartered-accounts-annual-conference",

"2024/november/clare-lombardelli-speech-at-the-3rd-boe-watchers-conference",
"2024/november/dave-ramsden-speech-on-monetary-policy-at-the-university-of-leeds",
"2024/november/andrew-bailey-speech-at-the-annual-financial-and-professional-services-dinner",
"2024/november/swati-dhingra-panellist-at-third-boe-watchers-conference-inflation-dynamics",
"2024/november/catherine-l-mann-society-of-professional-economists-annual-conference",

"2024/december/dave-ramsden-speech-at-omfif-on-financial-stability-and-the-boe-toolkit",

"2025/january/alan-taylor-speech-at-leeds-university-inflation-dynamics-and-outlook",
"2025/january/sarah-breeden-speech-at-the-university-of-edinburgh",
"2025/january/andrew-bailey-remarks-at-bretton-woods-institutions-cambridge",

"2025/february/dave-ramsden-keynote-speech-stellenbosch-university-on-monetary-policy-geopolitical-fragmentation",
"2025/february/swati-dhingra-speech-dow-lecture-niesr-trade-fragmentation-and-monetary-policy",
"2025/february/megan-greene-speech-at-the-institute-of-directors",
"2025/february/andrew-bailey-keynote-speech-university-of-chicago-booth-school-of-business",
"2025/february/catherine-l-mann-speech-at-leeds-beckett-university-economic-prospects",

"2025/march/andrew-bailey-university-of-leicester-chancellors-distinguished-lecture",
"2025/march/catherine-l-mann-keynote-lecture-reserve-bank-of-new-zealand-research-conference",

"2025/may/andrew-bailey-speech-followed-by-fireside-chat-with-francine-lacqua-bloomberg",
"2025/may/huw-pill-speech-at-the-barclays-briefing",
"2025/may/central-bank-communications-and-uncertainty-remarks-by-clare-lombardelli",
"2025/may/swati-dhingra-speech-at-the-new-economics-foundation-conference",
"2025/may/catherine-l-mann-panellist-at-the-boe-bank-watchers-conference",
"2025/may/megan-greene-panellist-at-the-bank-of-england-bank-watchers-conference",
"2025/may/clare-lombardelli-keynote-speech-at-the-bank-of-england-bank-watchers-conference",
"2025/may/andrew-bailey-keynote-address-at-the-reykjavik-economic-conference-2025",
"2025/may/sarah-breeden-panellist-at-the-global-finance-technology-network",

"2025/june/dave-ramsden-speech-and-panellist-at-the-barclays-cepr-monetary-policy-forum-2025",
"2025/june/megan-greene-speech-at-niesr-monetary-policy-implications-of-differences-in-central-bank-balance",
"2025/june/andrew-bailey-speech-at-the-annual-research-conference-kyiv",
"2025/june/catherine-l-mann-fireside-chat-at-the-federal-reserve-board-of-governors",

"2025/july/andrew-bailey-speech-at-the-annual-financial-and-professional-services-dinner-mansion-house",
"2025/july/meaning-of-reserve-currency-remarks-andrew-bailey",
"2025/july/alan-taylor-panellist-at-ecb-forum-on-central-banking-2025",

"2025/september/megan-greene-university-of-glasgow-business-school",
"2025/september/huw-pill-fireside-chat-at-the-inaugural-pictet-research-institute-symposium",
"2025/september/sarah-breeden-speech-cardiff-business-school-afternoon-briefing",
"2025/september/sarah-breeden-keynote-speech-at-the-boe-and-warwick-business-school",

"2025/october/catherine-l-mann-keynote-speech-at-resolution-foundation",
"2025/october/swati-dhingra-speech-at-the-central-bank-of-ireland-escb-cluster-2-academic-conference",
"2025/october/global-economic-outlook-panel-panel-remarks-by-andrew-bailey",
"2025/october/sarah-breeden-panellist-at-fintech-foundation-2025-dc-fiintech-week",
"2025/october/alan-taylor-remarks-and-fireside-chat-with-gillian-tett-at-cambridge",
"2025/october/andrew-bailey-keynote-speech-at-scotland-global-investment-summit-2025",
"2025/october/andrew-bailey-keynote-speech-at-klaas-knott-farewell-symposium",

"2026/january/alan-taylor-speech-at-the-national-university-of-singapore",
"2026/january/dave-ramsden-speech-at-kings-college-london-the-evolution-of-resolution",
"2026/january/andrew-bailey-meeting-of-the-bellagio-group-2026-at-the-boe",
"2026/january/megan-greene-speech-at-the-resolution-foundation-worlds-apart",

"2026/february/sarah-breeden-keynote-speech-at-the-city-financial-annual-payments-regulation-and-innovation-summit",
"2026/february/andrew-bailey-speech-at-the-imf-saudi-ministry-of-finance",

"2026/march/speech-by-alan-taylor-getting-the-right-directions",
"2026/march/andrew-bailey-opening-remarks-at-financial-stability-board-payments-summit",
"2026/march/huw-pill-speech-at-national-bank-of-the-republic-of-north-macedonia-and-suerf-conference",
"2026/march/alan-taylor-exante-datas-10-year-anniversary-macro-conference",

"2026/april/andrew-bailey-panellist-at-columbia-university-new-york",
"2026/april/sarah-breeden-at-the-program-on-international-financial-systems-and-harvard-law-school",

"2026/may/catherine-l-mann-speech-at-the-london-school-of-economics",
"2026/may/slides-from-huw-pill-fireside-chat-at-natwest",
"2026/may/sarah-breeden-speech-at-city-week-the-future-of-money-in-a-digital-world",
"2026/may/andrew-bailey-speech-at-cutlers-feast-sheffield",
"2026/may/andrew-bailey-speech-at-the-reykjavik-2026-economic-conference",

"2026/june/megan-greene-speech-at-university-of-derby-business-school",
"2026/june/alan-taylor-speech-at-the-barclays-and-centre-for-economic-policy-research",
"2026/june/swati-dhingra-panel-at-the-world-resources-institute-workshop",

"2026/july/andrew-bailey-speech-at-manison-house",

"2026/september/remarks-at-the-edinburgh-chamber-of-commerce",
"2026/september/andrew-bailey-keynote-speech-at-lse-trium-anniversary-conference",
"2026/september/clare-lombardelli-speech-at-the-sixth-biennial-conference-poland",
"2026/september/dave-ramsden-speech-on-quantitative-tightening",
"2026/september/searching-for-signposts-speech-by-alan-taylor",
"2026/october/catherine-mann-nomura-investor-conference",
"2026/october/andrew-bailey-speech-at-the-istanbul-economic-forum-central-bank-of-the-republic-of-turkey-istanbul"


)

foreach ($slug in $speechSlugs) {
    $url = if ($slug -match '^https?://') { $slug } else { $base + $slug }
    Write-Host "Fetching $url"

    try {
        $html = Invoke-WebRequest -Uri $url -UseBasicParsing
    } catch {
        Write-Host "Failed to fetch $url"
        continue
    }

    $sourcePath = ([uri]$url).AbsolutePath
    $fileName = Split-Path -Path $sourcePath.TrimEnd('/') -Leaf
    $contentType = ($html.Headers['Content-Type'] -split ';' | Select-Object -First 1).Trim()

    if ($contentType -match '^(application/pdf|application/vnd\.ms-powerpoint|application/vnd\.openxmlformats-officedocument\.presentationml\.presentation)$' -or $sourcePath -match '\.(pdf|pptx?|ppsx?)$') {
        if ($fileName -notmatch '\.(pdf|pptx?|ppsx?)$') {
            $fileName += '.pdf'
        }

        $yearMatch = [regex]::Match($sourcePath, '(?<!\d)(?:19|20)\d{2}(?!\d)')
        $year = if ($yearMatch.Success) { $yearMatch.Value } else { 'unknown-year' }
        $yearDirectory = Join-Path -Path $outputRoot -ChildPath $year
        if (!(Test-Path $yearDirectory)) {
            New-Item -ItemType Directory -Path $yearDirectory | Out-Null
        }

        $attachmentPath = Join-Path -Path $yearDirectory -ChildPath $fileName
        Invoke-WebRequest -Uri $url -OutFile $attachmentPath
        Write-Host "Saved attachment: $attachmentPath"
        continue
    }

    $yearMatch = [regex]::Match($sourcePath, '(?<!\d)(?:19|20)\d{2}(?!\d)')
    if ($yearMatch.Success) {
        $year = $yearMatch.Value
    } else {
        $dateMatch = [regex]::Match($html.Content, '<time[^>]*\bdatetime\s*=\s*["'']([^"'' ]+)["'']', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if (!$dateMatch.Success) {
            Write-Host "Could not determine publication date for $url"
            continue
        }

        $year = $dateMatch.Groups[1].Value.Substring(0,4)
    }

    $yearDirectory = Join-Path -Path $outputRoot -ChildPath $year

    if (!(Test-Path $yearDirectory)) {
        New-Item -ItemType Directory -Path $yearDirectory | Out-Null
    }

    # Restrict candidate PDF links to the same year/month as this speech, so that
    # PDFs cited in footnotes/body text (which point at other speeches' files)
    # aren't mistaken for this speech's own attachment.
    $monthMatch = [regex]::Match($sourcePath, '/speech/(\d{4})/([a-z]+)/')
    $pathScope = if ($monthMatch.Success) { "/files/speech/$($monthMatch.Groups[1].Value)/$($monthMatch.Groups[2].Value)/" } else { $null }

    $speechLink = $html.Links | Where-Object {
        $_.href -match '\.(pdf|pptx?|ppsx?)(?:\?|$)' -and
        $_.href -match '/-/media/boe/files/speech/' -and
        (!$pathScope -or $_.href -match [regex]::Escape($pathScope)) -and
        "$(($_.InnerText) -join ' ') $($_.href)" -notmatch '(?i)q\s*&?\s*a|transcript|appendix|annex|slides?|presentation|report|publication'
    } | Select-Object -First 1

    if (!$speechLink) {
        # Some speeches (e.g. conference panel remarks) are published only as a
        # slide deck, with no separate full-text version. In that case, fall
        # back to accepting a "slides" PDF rather than skipping the content.
        $speechLink = $html.Links | Where-Object {
            $_.href -match '\.(pdf|pptx?|ppsx?)(?:\?|$)' -and
            $_.href -match '/-/media/boe/files/speech/' -and
            (!$pathScope -or $_.href -match [regex]::Escape($pathScope)) -and
            "$(($_.InnerText) -join ' ') $($_.href)" -notmatch '(?i)q\s*&?\s*a|transcript|appendix|annex|presentation|report|publication'
        } | Select-Object -First 1
    }

    if ($speechLink) {
        $speechUrl = ([uri]::new([uri]$url, $speechLink.href)).AbsoluteUri
        $speechFileName = Split-Path -Path (([uri]$speechUrl).AbsolutePath) -Leaf
        $speechPath = Join-Path -Path $yearDirectory -ChildPath $speechFileName

        try {
            Invoke-WebRequest -Uri $speechUrl -OutFile $speechPath
            Write-Host "Saved speech: $speechPath"
        } catch {
            Write-Host "Failed to download speech: $speechUrl"
        }
        continue
    }

    $htmlPath = Join-Path -Path $yearDirectory -ChildPath "$fileName.html"
    $html.Content | Out-File -FilePath $htmlPath -Encoding UTF8
    Write-Host "Saved HTML: $htmlPath"
}
