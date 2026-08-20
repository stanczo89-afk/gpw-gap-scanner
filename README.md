# GPW Gap Scanner v0.2

Testowy skaner dolnych luk otwarcia GPW.

Najważniejsze zmiany:
- próba odświeżenia uniwersum ze strony GPW `https://www.gpw.pl/spolki`,
- `tickers.csv` pozostaje fallbackiem i miejscem korekt tickerów Yahoo,
- filtr luki `< -0,5%`,
- minimalny obrót 10 000 PLN,
- pole `turnover_pln`,
- snapshoty 09:02 / 09:07 / 09:12 czasu polskiego,
- ręczne `Run workflow` działa o dowolnej porze,
- harmonogram automatyczny nie ma już stałego `FORCE_RUN`.

Uwaga: Yahoo/yfinance to darmowe źródło testowe i dane GPW mogą być opóźnione.
Po uruchomieniu sprawdź `universe_count` w `data/latest.json`. GPW pokazuje obecnie 403 spółki na Głównym Rynku; jeśli automatyczne odkrywanie zwróci wyraźnie mniej, w v0.3 dodamy pełną obsługę paginacji listy GPW.
