# Portal de Notícias pessoal

Site estático no GitHub Pages, atualizado por GitHub Actions. Sem servidor.

## Rodar localmente
```
pip install -r requirements.txt
python -m src.coletar_noticias && python -m src.build
python -m http.server -d docs
```

## Estado
- [x] Etapa 1: esqueleto, RSS, página com abas e tema claro/escuro
- [x] Etapa 2: Gemini (agrupar/resumir, enquadramento na política)
- [x] Etapa 3: Banco Central (Selic, IPCA, dólar PTAX, Focus) — workflow diário
- [x] Etapa 4: futebol (7 ligas via football-data.org, Flamengo via ESPN + notícias do ge)
- [ ] Etapas 5–6: F1/NBA/NBB, onde assistir

Fontes em `config/feeds.yml`. Chaves apenas como GitHub Secrets (`GEMINI_API_KEY`, `FOOTBALL_DATA_KEY`).
