# GPW Gap Scanner

Darmowy testowy skaner dolnych luk otwarcia na GPW.

## Cel

Projekt ma przez 1-2 miesiące zbierać sygnały do testu strategii gap-fill bez automatycznego składania zleceń.

## Jak działa v0.1

- pobiera dane przez `yfinance`,
- porównuje dzisiejsze otwarcie z poprzednim zamknięciem,
- filtruje dolne luki większe niż 0,5%,
- wymaga dodatniego wolumenu,
- zapisuje bieżący wynik do `data/latest.json`,
- dopisuje kandydatów do `data/history.csv`,
- GitHub Actions wykonuje snapshoty około 09:02, 09:07 i 09:12 czasu polskiego.

## Ważne

Darmowe dane Yahoo Finance dla GPW mogą być opóźnione około 15 minut. To źródło testowe, a nie profesjonalny feed real-time.

`tickers.csv` zawiera na razie listę startową. Kolejny etap to uzupełnienie jej do pełnej listy rynku głównego GPW.

## Ręczne uruchomienie

```bash
pip install -r requirements.txt
FORCE_RUN=1 python scanner.py
```

W Windows PowerShell:

```powershell
$env:FORCE_RUN="1"
python scanner.py
```

## Struktura

```text
gpw-gap-scanner/
├── scanner.py
├── requirements.txt
├── tickers.csv
├── data/
│   ├── latest.json
│   └── history.csv
└── .github/
    └── workflows/
        └── scanner.yml
```
