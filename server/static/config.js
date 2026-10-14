// Ghi đè địa chỉ API khi UI được host ở nơi khác (Vercel...). deploy/vercel/build.py tự sinh file này.
window.APP_CONFIG = window.APP_CONFIG || { apiBase: "" };
