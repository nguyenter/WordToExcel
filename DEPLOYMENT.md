# Deployment Guide - Render

## Environment Variables

Khi deploy lên Render, bạn cần thêm các environment variables sau vào Render Dashboard:

### 1. Truy cập Render Dashboard
- Đăng nhập vào https://dashboard.render.com/
- Chọn web service của bạn
- Vào tab "Environment"
- Thêm các biến môi trường sau:

### 2. Flask Configuration
```
SECRET_KEY=your-secret-key-here
MAX_UPLOAD_MB=8
PUBLIC_BASE_URL=https://your-app-name.onrender.com
FILE_TTL_MINUTES=15
DOWNLOAD_TOKEN_TTL_MINUTES=3
```

### 3. API Key Configuration (để bypass payment)
```
API_KEY=your-api-key-here
```

### 4. Supabase Configuration
```
SUPABASE_URL=your-supabase-url-here
SUPABASE_KEY=your-supabase-key-here
```

### 5. PayOS Configuration
```
PAYOS_CLIENT_ID=your-payos-client-id-here
PAYOS_API_KEY=your-payos-api-key-here
PAYOS_CHECKSUM_KEY=your-payos-checksum-key-here
```

## Lưu ý quan trọng

- **KHÔNG** đẩy file `.env` lên GitHub/GitLab
- File `.env` đã được thêm vào `.gitignore` để tránh bị commit
- File `.env.example` là mẫu, không chứa sensitive information
- Khi deploy, Render sẽ tự động load environment variables từ dashboard

## Local Development

Để chạy local:
```bash
# Copy file mẫu
cp .env.example .env

# Edit file .env với các giá trị thực tế của bạn
# Sau đó chạy:
python index.py
```
