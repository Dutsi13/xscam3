import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


BOT_TOKEN = "8648072212:AAEyM42o3-MaMh-3Tj88Obg2ByY-tXjqsO8"
STATE_FILE = Path(__file__).with_name("bot_memory.json")
LEGACY_STATE_FILE = Path(__file__).with_name("bot_state.json")

CODE_ADMINS = [
    {"id": 7785932103, "username": "stv18"},
]

DEFAULT_START_TEXT = (
    "👤Добро Пожаловать в X-SCAM (https://t.me/Xscam_Community)\n\n"
    "👋 Привет, ты попал в бота от проекта X-Scam (https://t.me/Xscam_Community)\n\n"
    "⚠️Если вас обманули, вы можете слить скамера в предложку "
    "(https://t.me/+ywX887f10lU4NTY6)\n\n"
    "❗ У нас есть чат для Поиска гарантов (https://t.me/+MEzPWQcIl5djNmE6). "
    "Там всегда найдёте гаранта, который поможет безопасно купить/продать игровую ценность.\n\n"
    "🔎Проверить на скам: /check @Тег_Человека (или ответом на сообщение)\n"
    "Проверить себя: /me"
)

DEFAULT_MENU_BUTTONS = [
    ("profile", "Мой Профиль", "Здесь будет ваш профиль."),
    ("guarantors", "Список Гарантов", "Здесь будет список гарантов."),
    ("deal", "Провести сделку через гаранта", "Здесь будет инструкция по сделке через гаранта."),
    ("report", "Слить Скамера", "Здесь будет форма для отправки жалобы на скамера."),
    ("commands", "Команды", "Здесь будет список команд бота."),
    ("about", "О проекте", "Здесь будет информация о проекте X-SCAM."),
]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

state = {
    "admins": [],
    "known_users": {},
    "start_message": {
        "text": DEFAULT_START_TEXT,
        "photo_file_id": None,
        "sticker_file_id": None,
        "buttons": [],
    },
    "sections": {},
    "menu_buttons": {},
}


def read_json(path: Path) -> Optional[Dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Could not read %s", path)
        return None


def save_json(path: Path, payload: Dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_username(username: Optional[str]) -> Optional[str]:
    if not username:
        return None
    return username.lower().lstrip("@")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9а-яА-Я_-]+", "_", text.strip().lower())
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "section"


def default_menu_buttons() -> Dict[str, Dict]:
    result = {}
    for key, label, text in DEFAULT_MENU_BUTTONS:
        result[key] = {
            "label": label,
            "aliases": [],
            "text": text,
            "photo_file_id": None,
            "sticker_file_id": None,
            "buttons": [],
        }
    return result


def default_state() -> Dict:
    return {
        "admins": [],
        "known_users": {},
        "start_message": {
            "text": DEFAULT_START_TEXT,
            "photo_file_id": None,
            "sticker_file_id": None,
            "buttons": [],
        },
        "sections": {},
        "menu_buttons": default_menu_buttons(),
    }


def ensure_state_shape() -> None:
    base = default_state()
    for key, value in base.items():
        if key not in state:
            state[key] = value

    state["known_users"] = state.get("known_users", {})
    state["sections"] = state.get("sections", {})
    state["menu_buttons"] = state.get("menu_buttons", {})

    sm = state.get("start_message", {})
    state["start_message"] = {
        "text": sm.get("text") or DEFAULT_START_TEXT,
        "photo_file_id": sm.get("photo_file_id"),
        "sticker_file_id": sm.get("sticker_file_id"),
        "buttons": sm.get("buttons", []),
    }

    merged_admins = []
    seen = set()
    for admin in CODE_ADMINS + state.get("admins", []):
        try:
            admin_id = int(admin["id"])
        except Exception:
            continue
        if admin_id in seen:
            continue
        seen.add(admin_id)
        merged_admins.append(
            {"id": admin_id, "username": normalize_username(admin.get("username"))}
        )
    state["admins"] = merged_admins

    for slug, section in list(state["sections"].items()):
        state["sections"][slug] = {
            "title": section.get("title") or slug,
            "text": section.get("text") or f"Раздел {section.get('title') or slug}",
            "photo_file_id": section.get("photo_file_id"),
            "sticker_file_id": section.get("sticker_file_id"),
            "buttons": section.get("buttons", []),
        }

    defaults = default_menu_buttons()
    for key, fallback in defaults.items():
        item = state["menu_buttons"].get(key, {})
        state["menu_buttons"][key] = {
            "label": item.get("label") or fallback["label"],
            "aliases": item.get("aliases", []),
            "text": item.get("text") or fallback["text"],
            "photo_file_id": item.get("photo_file_id"),
            "sticker_file_id": item.get("sticker_file_id"),
            "buttons": item.get("buttons", []),
        }


def load_state() -> None:
    global state
    loaded = read_json(STATE_FILE)
    if loaded is None and LEGACY_STATE_FILE.exists():
        loaded = read_json(LEGACY_STATE_FILE)
    state = loaded or default_state()
    ensure_state_shape()
    save_state()


def save_state() -> None:
    save_json(STATE_FILE, state)


def is_admin(user_id: int) -> bool:
    return any(admin["id"] == user_id for admin in state["admins"])


def register_user(update: Update) -> None:
    user = update.effective_user
    if not user:
        return
    username = normalize_username(user.username)
    if not username:
        return
    payload = {"id": user.id, "username": username, "full_name": user.full_name}
    if state["known_users"].get(username) != payload:
        state["known_users"][username] = payload
        save_state()


def parse_buttons(raw: str) -> Tuple[List[List[Dict[str, str]]], List[str]]:
    errors: List[str] = []
    rows: Dict[int, Dict[int, Dict[str, str]]] = {}
    text = raw.strip()
    if not text or text == "-":
        return [], errors

    auto_row = 1
    for idx, line in enumerate(text.splitlines(), start=1):
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 2:
            btn_text, url = parts
            row_idx, col_idx = auto_row, 1
            auto_row += 1
        elif len(parts) == 3:
            pos, btn_text, url = parts
            if "," not in pos:
                errors.append(f"Строка {idx}: формат позиции row,col")
                continue
            row_s, col_s = [x.strip() for x in pos.split(",", 1)]
            if not row_s.isdigit() or not col_s.isdigit():
                errors.append(f"Строка {idx}: row и col должны быть числами")
                continue
            row_idx, col_idx = int(row_s), int(col_s)
        else:
            errors.append(f"Строка {idx}: используй `текст | ссылка` или `row,col | текст | ссылка`")
            continue

        if not btn_text:
            errors.append(f"Строка {idx}: пустой текст кнопки")
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            errors.append(f"Строка {idx}: ссылка должна начинаться с http:// или https://")
            continue

        rows.setdefault(row_idx, {})
        if col_idx in rows[row_idx]:
            errors.append(f"Строка {idx}: позиция {row_idx},{col_idx} уже занята")
            continue
        rows[row_idx][col_idx] = {"text": btn_text, "url": url}

    result = []
    for row_idx in sorted(rows):
        result.append([rows[row_idx][col_idx] for col_idx in sorted(rows[row_idx])])
    return result, errors


def make_markup(button_rows: List[List[Dict[str, str]]]) -> Optional[InlineKeyboardMarkup]:
    if not button_rows:
        return None
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(btn["text"], url=btn["url"]) for btn in row]
            for row in button_rows
        ]
    )


def build_user_keyboard() -> ReplyKeyboardMarkup:
    rows: List[List[KeyboardButton]] = []
    order = [key for key, _, _ in DEFAULT_MENU_BUTTONS]
    for i in range(0, len(order), 2):
        rows.append([KeyboardButton(state["menu_buttons"][key]["label"]) for key in order[i : i + 2]])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)


def build_start_markup() -> Optional[InlineKeyboardMarkup]:
    rows: List[List[InlineKeyboardButton]] = []
    for row in state["start_message"].get("buttons", []):
        rows.append([InlineKeyboardButton(btn["text"], url=btn["url"]) for btn in row])
    for slug, section in state["sections"].items():
        rows.append([InlineKeyboardButton(section["title"], callback_data=f"open_section:{slug}")])
    return InlineKeyboardMarkup(rows) if rows else None


def build_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Изменить /start текст", callback_data="admin:start:text")],
            [InlineKeyboardButton("Изменить /start фото", callback_data="admin:start:photo")],
            [InlineKeyboardButton("Изменить /start стикер", callback_data="admin:start:sticker")],
            [InlineKeyboardButton("Изменить /start кнопки", callback_data="admin:start:buttons")],
            [InlineKeyboardButton("Пользовательские кнопки", callback_data="admin:menu_buttons")],
            [InlineKeyboardButton("Вкладки", callback_data="admin:sections")],
            [InlineKeyboardButton("Админы", callback_data="admin:list")],
        ]
    )


def build_admin_sections_menu() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Добавить вкладку", callback_data="admin:section:new")]]
    for slug, section in state["sections"].items():
        rows.append([InlineKeyboardButton(section["title"], callback_data=f"admin:section:{slug}")])
    rows.append([InlineKeyboardButton("Назад", callback_data="admin:menu")])
    return InlineKeyboardMarkup(rows)


def build_admin_section_menu(slug: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Текст вкладки", callback_data=f"admin:section_text:{slug}")],
            [InlineKeyboardButton("Фото вкладки", callback_data=f"admin:section_photo:{slug}")],
            [InlineKeyboardButton("Стикер вкладки", callback_data=f"admin:section_sticker:{slug}")],
            [InlineKeyboardButton("Кнопки вкладки", callback_data=f"admin:section_buttons:{slug}")],
            [InlineKeyboardButton("Удалить вкладку", callback_data=f"admin:section_delete:{slug}")],
            [InlineKeyboardButton("Назад", callback_data="admin:sections")],
        ]
    )


def build_admin_menu_buttons_list() -> InlineKeyboardMarkup:
    rows = []
    for key, _, _ in DEFAULT_MENU_BUTTONS:
        rows.append([InlineKeyboardButton(state["menu_buttons"][key]["label"], callback_data=f"admin:menu_button:{key}")])
    rows.append([InlineKeyboardButton("Назад", callback_data="admin:menu")])
    return InlineKeyboardMarkup(rows)


def build_admin_menu_button_menu(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Изменить название", callback_data=f"admin:menu_button_label:{key}")],
            [InlineKeyboardButton("Изменить текст", callback_data=f"admin:menu_button_text:{key}")],
            [InlineKeyboardButton("Изменить фото", callback_data=f"admin:menu_button_photo:{key}")],
            [InlineKeyboardButton("Изменить стикер", callback_data=f"admin:menu_button_sticker:{key}")],
            [InlineKeyboardButton("Изменить inline-кнопки", callback_data=f"admin:menu_button_buttons:{key}")],
            [InlineKeyboardButton("Назад", callback_data="admin:menu_buttons")],
        ]
    )


def admin_text() -> str:
    lines = ["Админы:"]
    for admin in state["admins"]:
        uname = f"@{admin['username']}" if admin.get("username") else "без username"
        lines.append(f"• {admin['id']} - {uname}")
    return "\n".join(lines)


def sections_text() -> str:
    if not state["sections"]:
        return "Вкладок пока нет."
    lines = ["Текущие вкладки:"]
    for slug, section in state["sections"].items():
        lines.append(f"• {section['title']} (`{slug}`)")
    return "\n".join(lines)


def menu_buttons_text() -> str:
    lines = ["Пользовательские кнопки:"]
    for key, _, _ in DEFAULT_MENU_BUTTONS:
        lines.append(f"• {state['menu_buttons'][key]['label']} (`{key}`)")
    return "\n".join(lines)


def menu_button_detail(key: str) -> str:
    item = state["menu_buttons"][key]
    aliases = item.get("aliases", [])
    alias_text = "\n".join(f"• {a}" for a in aliases) if aliases else "нет"
    return f"Кнопка: {item['label']}\n\nСтарые названия:\n{alias_text}\n\nТекст:\n{item['text']}"


async def send_content(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    photo_file_id: Optional[str] = None,
    sticker_file_id: Optional[str] = None,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    if photo_file_id:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=photo_file_id,
            caption=text,
            reply_markup=reply_markup,
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )

    if sticker_file_id:
        await context.bot.send_sticker(chat_id=chat_id, sticker=sticker_file_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    await send_content(
        chat_id=update.effective_chat.id,
        context=context,
        text=state["start_message"]["text"],
        photo_file_id=state["start_message"].get("photo_file_id"),
        sticker_file_id=state["start_message"].get("sticker_file_id"),
        reply_markup=build_start_markup(),
    )
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Выберите нужный раздел на клавиатуре ниже.",
        reply_markup=build_user_keyboard(),
    )


async def check_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    await update.message.reply_text("Команда /check пока заглушка.")


async def me_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    await update.message.reply_text("Команда /me пока заглушка.")


async def admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администраторам.")
        return
    context.user_data.clear()
    await update.message.reply_text(admin_text() + "\n\nВыбери, что хочешь настроить:", reply_markup=build_admin_menu())


async def give_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда доступна только администраторам.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /giveadmin @username")
        return
    username = normalize_username(context.args[0])
    if not username:
        await update.message.reply_text("Укажи username: /giveadmin @username")
        return
    known = state["known_users"].get(username)
    if not known:
        await update.message.reply_text("Пусть пользователь сначала напишет боту /start.")
        return
    uid = int(known["id"])
    if is_admin(uid):
        await update.message.reply_text("Он уже админ.")
        return
    state["admins"].append({"id": uid, "username": username})
    save_state()
    await update.message.reply_text(f"Админ добавлен: @{username}")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""

    if data.startswith("open_section:"):
        slug = data.split("open_section:", 1)[1]
        section = state["sections"].get(slug)
        if not section:
            await query.message.reply_text("Вкладка не найдена.")
            return
        await send_content(
            chat_id=query.message.chat_id,
            context=context,
            text=section["text"],
            photo_file_id=section.get("photo_file_id"),
            sticker_file_id=section.get("sticker_file_id"),
            reply_markup=make_markup(section.get("buttons", [])),
        )
        return

    if not is_admin(update.effective_user.id):
        await query.message.reply_text("Только админ.")
        return

    if data == "admin:menu":
        context.user_data.clear()
        await query.edit_message_text(admin_text() + "\n\nВыбери, что хочешь настроить:", reply_markup=build_admin_menu())
        return

    if data == "admin:list":
        await query.edit_message_text(admin_text() + "\n\nКоманда: /giveadmin @username", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="admin:menu")]]))
        return

    if data == "admin:sections":
        await query.edit_message_text(sections_text(), reply_markup=build_admin_sections_menu())
        return

    if data == "admin:menu_buttons":
        await query.edit_message_text(menu_buttons_text(), reply_markup=build_admin_menu_buttons_list())
        return

    if data == "admin:start:text":
        context.user_data["admin_action"] = "start_text"
        await query.message.reply_text("Пришли новый текст для /start.")
        return

    if data == "admin:start:photo":
        context.user_data["admin_action"] = "start_photo"
        await query.message.reply_text("Пришли фото для /start или `-` чтобы убрать.")
        return

    if data == "admin:start:sticker":
        context.user_data["admin_action"] = "start_sticker"
        await query.message.reply_text("Пришли premium sticker для /start или `-` чтобы убрать.")
        return

    if data == "admin:start:buttons":
        context.user_data["admin_action"] = "start_buttons"
        await query.message.reply_text(
            "Пришли кнопки для /start.\n\n"
            "Формат:\n`Текст | https://example.com`\nили\n`1,1 | Текст | https://example.com`\n\n"
            "Отправь `-`, если кнопки не нужны."
        )
        return

    if data == "admin:section:new":
        context.user_data["admin_action"] = "section_new"
        await query.message.reply_text("Пришли название новой вкладки.")
        return

    if data.startswith("admin:section:"):
        slug = data.split("admin:section:", 1)[1]
        section = state["sections"].get(slug)
        if not section:
            await query.message.reply_text("Вкладка не найдена.")
            return
        await query.edit_message_text(f"Вкладка: {section['title']}\nВыбери, что изменить.", reply_markup=build_admin_section_menu(slug))
        return

    if data.startswith("admin:section_text:"):
        slug = data.split("admin:section_text:", 1)[1]
        context.user_data["admin_action"] = "section_text"
        context.user_data["section_slug"] = slug
        await query.message.reply_text("Пришли новый текст для вкладки.")
        return

    if data.startswith("admin:section_photo:"):
        slug = data.split("admin:section_photo:", 1)[1]
        context.user_data["admin_action"] = "section_photo"
        context.user_data["section_slug"] = slug
        await query.message.reply_text("Пришли фото для вкладки или `-` чтобы убрать.")
        return

    if data.startswith("admin:section_sticker:"):
        slug = data.split("admin:section_sticker:", 1)[1]
        context.user_data["admin_action"] = "section_sticker"
        context.user_data["section_slug"] = slug
        await query.message.reply_text("Пришли premium sticker для вкладки или `-` чтобы убрать.")
        return

    if data.startswith("admin:section_buttons:"):
        slug = data.split("admin:section_buttons:", 1)[1]
        context.user_data["admin_action"] = "section_buttons"
        context.user_data["section_slug"] = slug
        await query.message.reply_text(
            "Пришли кнопки для вкладки.\n\n"
            "Формат:\n`Текст | https://example.com`\nили\n`1,1 | Текст | https://example.com`\n\n"
            "Отправь `-`, если кнопки не нужны."
        )
        return

    if data.startswith("admin:section_delete:"):
        slug = data.split("admin:section_delete:", 1)[1]
        section = state["sections"].pop(slug, None)
        save_state()
        await query.message.reply_text(f"Удалена вкладка: {section['title'] if section else slug}")
        await query.message.reply_text(sections_text(), reply_markup=build_admin_sections_menu())
        return

    if data.startswith("admin:menu_button:"):
        key = data.split("admin:menu_button:", 1)[1]
        context.user_data["menu_button_key"] = key
        await query.edit_message_text(menu_button_detail(key), reply_markup=build_admin_menu_button_menu(key))
        return

    if data.startswith("admin:menu_button_label:"):
        key = data.split("admin:menu_button_label:", 1)[1]
        context.user_data["admin_action"] = "menu_button_label"
        context.user_data["menu_button_key"] = key
        await query.message.reply_text("Пришли новое название кнопки.")
        return

    if data.startswith("admin:menu_button_text:"):
        key = data.split("admin:menu_button_text:", 1)[1]
        context.user_data["admin_action"] = "menu_button_text"
        context.user_data["menu_button_key"] = key
        await query.message.reply_text("Пришли новый текст для этой кнопки.")
        return

    if data.startswith("admin:menu_button_photo:"):
        key = data.split("admin:menu_button_photo:", 1)[1]
        context.user_data["admin_action"] = "menu_button_photo"
        context.user_data["menu_button_key"] = key
        await query.message.reply_text("Пришли фото для этой кнопки или `-` чтобы убрать.")
        return

    if data.startswith("admin:menu_button_sticker:"):
        key = data.split("admin:menu_button_sticker:", 1)[1]
        context.user_data["admin_action"] = "menu_button_sticker"
        context.user_data["menu_button_key"] = key
        await query.message.reply_text("Пришли premium sticker для этой кнопки или `-` чтобы убрать.")
        return

    if data.startswith("admin:menu_button_buttons:"):
        key = data.split("admin:menu_button_buttons:", 1)[1]
        context.user_data["admin_action"] = "menu_button_buttons"
        context.user_data["menu_button_key"] = key
        await query.message.reply_text(
            "Пришли inline-кнопки для этой кнопки.\n\n"
            "Формат:\n`Текст | https://example.com`\nили\n`1,1 | Текст | https://example.com`\n\n"
            "Отправь `-`, если кнопки не нужны."
        )
        return


async def handle_user_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.message or not update.message.text:
        return False

    text = update.message.text.strip()
    for item in state["menu_buttons"].values():
        if text == item["label"] or text in item.get("aliases", []):
            await send_content(
                chat_id=update.effective_chat.id,
                context=context,
                text=item["text"],
                photo_file_id=item.get("photo_file_id"),
                sticker_file_id=item.get("sticker_file_id"),
                reply_markup=make_markup(item.get("buttons", [])),
            )
            return True
    return False


async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update)
    if not update.message:
        return

    action = context.user_data.get("admin_action")
    if action:
        if not is_admin(update.effective_user.id):
            return
    else:
        if await handle_user_action(update, context):
            return
        return

    if action == "start_text":
        if not update.message.text:
            await update.message.reply_text("Нужен обычный текст.")
            return
        state["start_message"]["text"] = update.message.text
        save_state()
        context.user_data.clear()
        await update.message.reply_text("Текст /start обновлен.")
        return

    if action == "start_photo":
        if update.message.photo:
            state["start_message"]["photo_file_id"] = update.message.photo[-1].file_id
        elif (update.message.text or "").strip() == "-":
            state["start_message"]["photo_file_id"] = None
        else:
            await update.message.reply_text("Пришли фото или `-`.")
            return
        save_state()
        context.user_data.clear()
        await update.message.reply_text("Фото /start обновлено.")
        return

    if action == "start_sticker":
        if update.message.sticker:
            state["start_message"]["sticker_file_id"] = update.message.sticker.file_id
        elif (update.message.text or "").strip() == "-":
            state["start_message"]["sticker_file_id"] = None
        else:
            await update.message.reply_text("Пришли sticker или `-`.")
            return
        save_state()
        context.user_data.clear()
        await update.message.reply_text("Стикер /start обновлен.")
        return

    if action == "start_buttons":
        rows, errors = parse_buttons(update.message.text or "")
        if errors:
            await update.message.reply_text("Ошибки:\n- " + "\n- ".join(errors))
            return
        state["start_message"]["buttons"] = rows
        save_state()
        context.user_data.clear()
        await update.message.reply_text("Кнопки /start обновлены.")
        return

    key = context.user_data.get("menu_button_key")
    menu_item = state["menu_buttons"].get(key) if key else None

    if action == "menu_button_label":
        label = (update.message.text or "").strip()
        if not label:
            await update.message.reply_text("Название не должно быть пустым.")
            return
        old = menu_item["label"]
        if old != label:
            aliases = menu_item.setdefault("aliases", [])
            if old not in aliases:
                aliases.append(old)
        menu_item["label"] = label
        save_state()
        context.user_data.clear()
        await update.message.reply_text("Название кнопки обновлено.")
        return

    if action == "menu_button_text":
        menu_item["text"] = (update.message.text or "").strip()
        save_state()
        context.user_data.clear()
        await update.message.reply_text("Текст кнопки обновлен.")
        return

    if action == "menu_button_photo":
        if update.message.photo:
            menu_item["photo_file_id"] = update.message.photo[-1].file_id
        elif (update.message.text or "").strip() == "-":
            menu_item["photo_file_id"] = None
        else:
            await update.message.reply_text("Пришли фото или `-`.")
            return
        save_state()
        context.user_data.clear()
        await update.message.reply_text("Фото кнопки обновлено.")
        return

    if action == "menu_button_sticker":
        if update.message.sticker:
            menu_item["sticker_file_id"] = update.message.sticker.file_id
        elif (update.message.text or "").strip() == "-":
            menu_item["sticker_file_id"] = None
        else:
            await update.message.reply_text("Пришли sticker или `-`.")
            return
        save_state()
        context.user_data.clear()
        await update.message.reply_text("Стикер кнопки обновлен.")
        return

    if action == "menu_button_buttons":
        rows, errors = parse_buttons(update.message.text or "")
        if errors:
            await update.message.reply_text("Ошибки:\n- " + "\n- ".join(errors))
            return
        menu_item["buttons"] = rows
        save_state()
        context.user_data.clear()
        await update.message.reply_text("Inline-кнопки обновлены.")
        return

    if action == "section_new":
        title = (update.message.text or "").strip()
        if not title:
            await update.message.reply_text("Название не должно быть пустым.")
            return
        base = slugify(title)
        slug = base
        idx = 2
        while slug in state["sections"]:
            slug = f"{base}_{idx}"
            idx += 1
        state["sections"][slug] = {
            "title": title,
            "text": f"Новый текст для вкладки «{title}»",
            "photo_file_id": None,
            "sticker_file_id": None,
            "buttons": [],
        }
        save_state()
        context.user_data.clear()
        await update.message.reply_text(f"Вкладка создана: {title}\nSlug: `{slug}`")
        return

    slug = context.user_data.get("section_slug")
    section = state["sections"].get(slug) if slug else None
    if not section:
        context.user_data.clear()
        await update.message.reply_text("Вкладка не найдена.")
        return

    if action == "section_text":
        section["text"] = (update.message.text or "").strip()
        save_state()
        context.user_data.clear()
        await update.message.reply_text("Текст вкладки обновлен.")
        return

    if action == "section_photo":
        if update.message.photo:
            section["photo_file_id"] = update.message.photo[-1].file_id
        elif (update.message.text or "").strip() == "-":
            section["photo_file_id"] = None
        else:
            await update.message.reply_text("Пришли фото или `-`.")
            return
        save_state()
        context.user_data.clear()
        await update.message.reply_text("Фото вкладки обновлено.")
        return

    if action == "section_sticker":
        if update.message.sticker:
            section["sticker_file_id"] = update.message.sticker.file_id
        elif (update.message.text or "").strip() == "-":
            section["sticker_file_id"] = None
        else:
            await update.message.reply_text("Пришли sticker или `-`.")
            return
        save_state()
        context.user_data.clear()
        await update.message.reply_text("Стикер вкладки обновлен.")
        return

    if action == "section_buttons":
        rows, errors = parse_buttons(update.message.text or "")
        if errors:
            await update.message.reply_text("Ошибки:\n- " + "\n- ".join(errors))
            return
        section["buttons"] = rows
        save_state()
        context.user_data.clear()
        await update.message.reply_text("Кнопки вкладки обновлены.")
        return


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception", exc_info=context.error)


def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError("Укажи BOT_TOKEN в telegram_post_bot.py")

    load_state()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("check", check_cmd))
    app.add_handler(CommandHandler("me", me_cmd))
    app.add_handler(CommandHandler("admins", admins))
    app.add_handler(CommandHandler("giveadmin", give_admin))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^(admin:|open_section:).*"))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO | filters.Sticker.ALL) & ~filters.COMMAND, handle_input))
    app.add_error_handler(error_handler)
    logger.info("Bot started")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
