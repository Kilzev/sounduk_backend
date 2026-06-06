#!/bin/bash
# deploy.sh - Развертывание изменений на боевой сервер

set -e

# Цвета
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SSH_HOST="root@185.76.242.73"
SSH_KEY="${HOME}/.ssh/sounduk_cursor"
REMOTE_PATH="/var/www/sounduk_backend"
LOCAL_PATH="/Users/ilya/Develope/mega_sounduk/sounduk_backend"
SSH_OPTS=(-i "$SSH_KEY" -o IdentitiesOnly=yes -o StrictHostKeyChecking=no)

echo -e "${BLUE}🚀 Sounduk API - Deployment${NC}"
echo "================================"

# Выбор файлов для развертывания
echo -e "\n${YELLOW}Какие файлы развернуть?${NC}"
echo "1) db_backup.py (исправление синхронизации БД)"
echo "2) main.py (обновления)"
echo "3) Все Python файлы (*.py)"
echo "4) Отмена"
read -p "Выбор (1-4): " deploy_choice

case $deploy_choice in
    1)
        FILES_TO_DEPLOY="db_backup.py"
        ;;
    2)
        FILES_TO_DEPLOY="main.py"
        ;;
    3)
        FILES_TO_DEPLOY="*.py"
        ;;
    4)
        echo -e "${RED}❌ Развертывание отменено${NC}"
        exit 0
        ;;
    *)
        echo -e "${RED}❌ Неверный выбор${NC}"
        exit 1
        ;;
esac

echo -e "\n${YELLOW}Файлы к развертыванию:${NC}"
echo "$FILES_TO_DEPLOY"

# Подтверждение
read -p "Продолжить? (y/n): " confirm
if [ "$confirm" != "y" ]; then
    echo -e "${RED}❌ Отменено${NC}"
    exit 0
fi

# Создание бэкапа на сервере
echo -e "\n${BLUE}📦 Создание бэкапа на сервере...${NC}"
ssh "${SSH_OPTS[@]}" "$SSH_HOST" \
    "cd $REMOTE_PATH && for f in $FILES_TO_DEPLOY; do [ -f \$f ] && cp -v \$f \$f.backup.$(date +%s); done"

# Копирование файлов на сервер
echo -e "\n${BLUE}📤 Копирование файлов на сервер...${NC}"
for file in $FILES_TO_DEPLOY; do
    if [ -f "$LOCAL_PATH/$file" ]; then
        scp "${SSH_OPTS[@]}" \
            "$LOCAL_PATH/$file" "$SSH_HOST:$REMOTE_PATH/$file"
        echo -e "${GREEN}✅ $file${NC}"
    fi
done

# Перезагрузка сервиса
echo -e "\n${YELLOW}Перезагрузить сервис uvicorn? (y/n)${NC}"
read -p "Выбор: " restart_choice

if [ "$restart_choice" = "y" ]; then
    echo -e "\n${BLUE}🔄 Перезагрузка uvicorn...${NC}"
    ssh "${SSH_OPTS[@]}" "$SSH_HOST" \
        "pkill -f '/var/www/sounduk_backend/venv/bin/uvicorn main:app' || true && sleep 2 && cd $REMOTE_PATH && \
        source venv/bin/activate && \
        nohup uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2 >> server.log 2>&1 &"
    sleep 3
    echo -e "${GREEN}✅ Сервис перезагружен${NC}"
fi

# Проверка статуса
echo -e "\n${BLUE}📊 Статус сервиса:${NC}"
ssh "${SSH_OPTS[@]}" "$SSH_HOST" \
    "ps aux | grep -E 'sounduk_backend.*uvicorn' | grep -v grep | tail -3"

echo -e "\n${GREEN}✅ Развертывание завершено!${NC}"
echo -e "🔗 API: https://api.sounduk.ru"
echo -e "📊 Swagger: https://api.sounduk.ru/docs"
