module.exports = {
  apps: [
    {
      name: "quantara-idx",
      cwd: "/Users/macbookairm22022/Documents/ChatGPT/AI QUANT IDX",
      script: ".venv/bin/python",
      args: "-m daphne -b 127.0.0.1 -p 8000 config.asgi:application",
      interpreter: "none",
      autorestart: true,
      max_restarts: 10,
      restart_delay: 2000,
      env: {
        DJANGO_SETTINGS_MODULE: "config.settings",
        PYTHONUNBUFFERED: "1",
      },
    },
  ],
};
