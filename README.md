# job_automation2

## Heroku Deployment

This application is configured for deployment on Heroku.

### Environment Variables

You will need to set the following environment variables in your Heroku application settings:

*   `SECRET_KEY`: A strong, random string used to secure sessions and cookies. You can generate one using `python -c 'import secrets; print(secrets.token_hex(32))'`.
*   `DATABASE_URL`: The connection URL for your PostgreSQL database provided by Heroku (e.g., `postgres://user:password@host:port/dbname`).
*   `OPENAI_API_KEY`: Your API key for OpenAI services, if you intend to use features that rely on it.
*   `PYTHON_VERSION`: While `runtime.txt` specifies the Python version, ensure your Heroku stack matches.

**Configuration from `config.json`:**

The application can load settings from a `config.json` file. However, for Heroku deployment, it's recommended to manage sensitive or environment-specific configurations using environment variables. The `config.json` file is included in `.gitignore` to prevent accidental commitment of sensitive data.

You may need to set additional environment variables corresponding to the settings found in `config.json`, particularly for:
- OpenAI settings (API key, model)
- Scraper settings (if they need to differ from local defaults or involve sensitive information like proxy details)
- File paths for data, logs, or cache (consider using `/tmp` for ephemeral storage on Heroku if these features are used in production)

For example, if your `config.json` locally has:
```json
{
  "openai_settings": {
    "api_key": "your_local_key",
    "model": "gpt-4-turbo"
  },
  "indeed_settings": {
    "log_file": "data/log.log"
  }
}
```
You would set environment variables on Heroku like:
- `OPENAI_API_KEY` = `your_actual_openai_key_for_heroku`
- `OPENAI_MODEL` = `gpt-4-turbo`
- `INDEED_LOG_FILE` = `/tmp/indeed_log.log` (and update `app.py` to read this from env var)

Adapt `app.py` to read these settings from environment variables, falling back to `config.json` defaults if appropriate for non-sensitive data.

### Procfile

The `Procfile` specifies how Heroku should run the application:
`web: gunicorn app:app`

This uses Gunicorn as the production web server.
