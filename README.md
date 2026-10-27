# Gorilla Watch (cloud, gratis, repository pubblico non indicizzato)

Controlla ogni 30 minuti i siti Gorilla Technology, Gorilla Tech Capital e IR.
Gira su GitHub Actions; la pagina è su GitHub Pages (con noindex); lo stato è anche in `STATUS.md`;
gli avvisi sono "Issues" (notifica push/email).

## Messa online (una volta sola)
1. Account su github.com (gratis) e app GitHub sul telefono.
2. Nuovo repository **pubblico** con nome non intuitivo (es. `gw-k7x92q`), vuoto, senza README.
3. Dal terminale, in questa cartella:
   ```
   git init -b main
   git add -A
   git commit -m "primo caricamento"
   git remote add origin https://github.com/TUO-UTENTE/NOME-REPO.git
   git push -u origin main
   ```
4. Settings -> Pages -> Source "Deploy from a branch" -> branch `main`, cartella `/docs` -> Save.
5. Tab Actions: abilita i workflow, apri "watch" -> "Run workflow" per il primo giro di prova.
6. Se il push del workflow fallisce: Settings -> Actions -> General -> Workflow permissions -> "Read and write".
7. App GitHub -> Settings -> Notifications: attiva push. Poi sul repo premi "Watch" -> Custom -> Issues.

Il sito sarà su `https://TUO-UTENTE.github.io/NOME-REPO/`.

## Facoltativo
Per controllare anche i nuovi documenti SEC: Settings -> Secrets and variables -> Actions -> New secret
`SEC_USER_AGENT` = `Nome Cognome tuamail@esempio.it`.

## Limiti noti
- Non è privato: chi ha il link (o trova il repository) vede pagina e avvisi. Contiene solo testi di pagine pubbliche
  di Gorilla. Il sito ha noindex/robots.txt, il repository non può essere escluso dall'indicizzazione.
- GitHub può ritardare le esecuzioni programmate di qualche minuto.
- Dopo 60 giorni senza attività GitHub può sospendere i workflow programmati: se non compaiono più commit
  "controllo ...", riattivali dalla tab Actions.
