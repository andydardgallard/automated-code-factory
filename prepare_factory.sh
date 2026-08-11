#!/usr/bin/env bash
# =============================================================================
# prepare_factory.sh — подготовка проекта к запуску Code Factory.
#
# Назначение: скопировать фабрику (.agents/) в проект, настроить .gitignore,
# при необходимости инициализировать git-репозиторий и проверить готовность.
#
# Использование:
#   ./prepare_factory.sh <путь-к-проекту>
#
# Пример:
#   ./prepare_factory.sh /home/adar/ai-factories/my-test-project
#
# Скрипт НЕ коммитит ничего. Все шаги безопасны и идемпотентны.
# =============================================================================
set -euo pipefail

# --- Пути -------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FACTORY_SRC="$SCRIPT_DIR/.agents"          # готовая фабрика (этот репозиторий)
PROJECT_DIR="${1:-}"

# --- Цвета ------------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { printf "${GREEN}%s${NC}\n" "$*"; }
warn()  { printf "${YELLOW}%s${NC}\n" "$*"; }
err()   { printf "${RED}%s${NC}\n" "$*" >&2; }

# --- Проверка аргумента ------------------------------------------------------
if [[ -z "$PROJECT_DIR" ]]; then
    err "Укажите путь к проекту:  ./prepare_factory.sh <путь-к-проекту>"
    exit 1
fi
if [[ ! -d "$PROJECT_DIR" ]]; then
    err "Папка проекта не найдена: $PROJECT_DIR"
    exit 1
fi
if [[ ! -d "$FACTORY_SRC" ]]; then
    err "Не найдена фабрика: $FACTORY_SRC (запускайте скрипт из папки from_kimi)"
    exit 1
fi

PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
info "==> Подготовка проекта: $PROJECT_DIR"

# --- 1. Git-репозиторий ------------------------------------------------------
if [[ -d "$PROJECT_DIR/.git" ]]; then
    info "    Git: репозиторий уже существует ✓"
else
    warn "    Git: репозитория нет — создаю git init"
    git -C "$PROJECT_DIR" init -b main
fi

# --- 2. Копирование фабрики --------------------------------------------------
if [[ -d "$PROJECT_DIR/.agents" ]]; then
    warn "    .agents/ уже существует — обновляю содержимое фабрики (без удаления лишнего)"
    mkdir -p "$PROJECT_DIR/.agents"
    # Копируем только то, чего нет, или перезаписываем устаревшее.
    # Безопасно: не трогаем пользовательские файлы в .agents/, которых нет в фабрике.
    cp -rn "$FACTORY_SRC"/. "$PROJECT_DIR/.agents/" 2>/dev/null || true
    # Принудительно обновляем ключевые файлы фабрики (они должны быть актуальны)
    for f in SKILL.md system.md code-factory.yaml models.yaml gen_code_changes_report.py; do
        src=$(find "$FACTORY_SRC" -name "$f" -type f | head -1 || true)
        if [[ -n "$src" ]]; then
            dst=$(find "$PROJECT_DIR/.agents" -name "$f" -type f | head -1 || true)
            if [[ -n "$dst" ]]; then cp -f "$src" "$dst"; else
                # сохраняем относительный путь внутри .agents/
                rel="${src#$FACTORY_SRC/}"
                mkdir -p "$PROJECT_DIR/.agents/$(dirname "$rel")"
                cp -f "$src" "$PROJECT_DIR/.agents/$rel"
            fi
        fi
    done
    # Справочники и сабагенты — копируем только недостающие
    for d in references assets sub-agents examples scripts; do
        if [[ -d "$FACTORY_SRC/$d" ]]; then
            mkdir -p "$PROJECT_DIR/.agents/$d"
            cp -rn "$FACTORY_SRC/$d"/. "$PROJECT_DIR/.agents/$d/" 2>/dev/null || true
        fi
    done
else
    info "    Фабрика: копирую .agents/ → $PROJECT_DIR/.agents"
    cp -r "$FACTORY_SRC" "$PROJECT_DIR/.agents"
fi

# --- 3. .gitignore -----------------------------------------------------------
GITIGNORE="$PROJECT_DIR/.gitignore"
NEED_GITIGNORE=false
for pat in ".code-factory/" "__pycache__/" "*.pyc"; do
    if [[ -f "$GITIGNORE" ]] && grep -qF "$pat" "$GITIGNORE"; then
        :
    else
        NEED_GITIGNORE=true
    fi
done

if [[ "$NEED_GITIGNORE" == true ]]; then
    warn "    .gitignore: добавляю runtime-паттерны фабрики"
    {
        [[ -f "$GITIGNORE" ]] && echo ""
        echo "# --- Code Factory runtime (auto-added by prepare_factory.sh) ---"
        echo ".code-factory/"
        echo "__pycache__/"
        echo "*.pyc"
    } >> "$GITIGNORE"
fi

# --- 4. Проверка готовности --------------------------------------------------
echo ""
info "==> Проверка готовности:"
echo "    • .agents/:            $([ -f "$PROJECT_DIR/.agents/skills/code-factory/SKILL.md" ] && echo 'OK ✓' || echo 'ОТСУТСТВУЕТ ✗')"
echo "    • .git/:               $([ -d "$PROJECT_DIR/.git" ] && echo 'OK ✓' || echo 'ОТСУТСТВУЕТ ✗')"
echo "    • .gitignore:          $(grep -qF '.code-factory/' "$PROJECT_DIR/.gitignore" 2>/dev/null && echo 'OK ✓' || echo 'нет .code-factory/ ✗')"
echo "    • git status:"
git -C "$PROJECT_DIR" status --short | head -20 || true
[[ -z "$(git -C "$PROJECT_DIR" status --short)" ]] && echo "      (чистое дерево)"
echo ""

info "==> Готово! Запуск фабрики:"
echo "    cd $PROJECT_DIR"
echo "    kimi"
echo "    # в чате: /flow:code-factory"
echo ""
echo "    Или сразу с задачей:"
echo "    kimi --agent-file .agents/agents/code-factory.yaml \"описание задачи\""
