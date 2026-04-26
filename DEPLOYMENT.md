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
API_KEY=nasani-2024-secret-key
```

### 4. Supabase Configuration
```
SUPABASE_URL=https://wmztulnvkpjfgohrwznz.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndtenR1bG52a3BqZmdvaHJ3em56Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3Njk0OTg1NiwiZXhwIjoyMDkyNTI1ODU2fQ.t1iiINdhc6YutfbAgyM3dxNb-Ns-R-Url6an666W5xk
```

### 5. PayOS Configuration
```
PAYOS_CLIENT_ID=9894e396-caa8-4e1e-97bf-bf4d7cb76039
PAYOS_API_KEY=b01d6f20-382a-4150-8352-71f234013b4f
PAYOS_CHECKSUM_KEY=83775809175ecf13387ea945e7efda8e883f8545a40e0a70d3d138c228cf4d3b
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
