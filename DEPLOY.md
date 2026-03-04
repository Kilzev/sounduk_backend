# Deployment Instructions for Sounduk Backend

This guide assumes you are deploying to a server running **Ubuntu 20.04** or **22.04**.

## 1. Server Connection
Connect to your server via SSH:
```bash
ssh username@your-server-ip
```

## 2. Install System Dependencies
Update packages and install Python, pip, Nginx, and git:
```bash
sudo apt update
sudo apt install -y python3-pip python3-venv nginx git certbot python3-certbot-nginx
```

## 3. Clone/Copy Project
Navigate to a directory (e.g., `/var/www` or your home folder):
```bash
cd /home/username
git clone https://github.com/your-repo/sounduk_backend.git
# OR copy files via SCP if no git repo
cd sounduk_backend
```

## 4. setup Python Environment
Create a virtual environment and install dependencies:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install gunicorn  # Recommended for production (optional, uvicorn is also fine)
```

## 5. Configuration (.env)
Create a `.env` file for your production secrets:
```bash
nano .env
```
Paste credentials:
```env
YOOKASSA_SHOP_ID=your_real_shop_id
YOOKASSA_SECRET_KEY=your_real_secret_key
# SECRET_KEY=generate_some_random_string
```

Create necessary directories:
```bash
mkdir logs
mkdir uploads
```

## 6. Setup Systemd Service (Keep App Running)
Create a service file to manage the application process automatically.

```bash
sudo nano /etc/systemd/system/sounduk.service
```

Paste the following content (change paths and username accordingly!):

```ini
[Unit]
Description=Gunicorn instance to serve Sounduk API
After=network.target

[Service]
User=root
Group=www-data
WorkingDirectory=/home/root/sounduk_backend
Environment="PATH=/home/root/sounduk_backend/.venv/bin"
EnvironmentFile=/home/root/sounduk_backend/.env
ExecStart=/home/root/sounduk_backend/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 4

[Install]
WantedBy=multi-user.target
```

Start and enable the service:
```bash
sudo systemctl start sounduk
sudo systemctl enable sounduk
sudo systemctl status sounduk
```

## 7. Setup Nginx (Reverse Proxy)
Configure Nginx to accept public requests and forward them to localhost:8000.

```bash
sudo nano /etc/nginx/sites-available/sounduk
```

Content:
```nginx
server {
    listen 80;
    server_name your-domain.com OR your-ip-address;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Increase upload size limit for mp3s
    client_max_body_size 50M;
}
```

Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/sounduk /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## 8. SSL (HTTPS) - Optional but Recommended
If you have a domain, secure it with Let's Encrypt:

```bash
sudo certbot --nginx -d your-domain.com
```

## 9. Verification
Your API should now be accessible at:
`http://your-server-ip/docs`
