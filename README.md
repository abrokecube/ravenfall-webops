# ravenfall-webops
Ravenfall browser automation server
Codebase now 80% ai generated!!!!!!

Configuration is done in a `.env` file.  
Place account credentials in a `credentials.csv` file, first column `username`, second colume `password`  
Config examples are in [.env.example](./.env.example) and [credentials_example.csv](./credentials_example.csv)  
Depends on Python 3.12+ and `uv`. To run just execute `uv run main.py` in a terminal.  
Developed with AI assistance  

### Automations
- Account login
- Get loyalty point count
- Redeem items in the loyalty shop

### Cookie caching
Authenticated sessions are cached in `.storage/` (one JSON file per account) so accounts
are not logged in from scratch on every session. Set `STORAGE_DIR` to change the location.
Delete a file to force that account to log in again on next use.
