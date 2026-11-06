#!/bin/bash
# AI-Agent PostgreSQL 每日备份脚本
# 保留最近 30 天备份，超过自动清理

BACKUP_DIR="/opt/AI-Agent/backups/postgres"
CONTAINER="aiagnet_postgres"
DB_USER="aiagnet"
DB_NAME="aiagnet"
RETENTION_DAYS=7
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/aiagnet_${TIMESTAMP}.sql.gz"
LOG_FILE="$BACKUP_DIR/backup.log"

# 日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 检查容器是否运行
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    log "ERROR: 容器 $CONTAINER 未运行，备份跳过"
    exit 1
fi

# 执行备份
log "INFO: 开始备份 $DB_NAME..."
if docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --clean --if-exists 2>>"$LOG_FILE" | gzip > "$BACKUP_FILE"; then
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    log "INFO: 备份完成 $BACKUP_FILE ($SIZE)"
else
    log "ERROR: pg_dump 失败"
    rm -f "$BACKUP_FILE"
    exit 1
fi

# 清理旧备份（保留最近 N 天）
log "INFO: 清理 ${RETENTION_DAYS} 天前的旧备份..."
find "$BACKUP_DIR" -name "aiagnet_*.sql.gz" -mtime +$RETENTION_DAYS -delete -print | while read f; do
    log "INFO: 删除旧备份 $f"
done

# 统计
TOTAL=$(ls -1 "$BACKUP_DIR"/aiagnet_*.sql.gz 2>/dev/null | wc -l)
log "INFO: 当前共 $TOTAL 个备份文件"
log "INFO: 备份流程结束"
