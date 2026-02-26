use std::sync::Arc;

use anyhow::Result;
use serde::{Deserialize, Serialize};
use teloxide::dispatching::dialogue::{Dialogue, InMemStorage};
use teloxide::dptree;
use teloxide::prelude::*;
use teloxide::types::{KeyboardButton, KeyboardMarkup};
use teloxide::utils::command::BotCommands;

use crate::config::Config;
use crate::rate_limit::SlidingWindowRateLimiter;
use crate::service::ServiceLayer;

#[derive(Clone)]
pub struct BotContext {
    pub config: Arc<Config>,
    pub services: Arc<ServiceLayer>,
    pub limiter: Arc<SlidingWindowRateLimiter>,
}

#[derive(Clone, Default, Serialize, Deserialize)]
pub enum State {
    #[default]
    Idle,
    AddPanelUrl,
    AddPanelUsername {
        login_url: String,
    },
    AddPanelPassword {
        login_url: String,
        username: String,
    },
    AddPanelTwoFactor {
        login_url: String,
        username: String,
        password: String,
    },
    BindPanelId,
    BindUserId {
        panel_id: i64,
    },
    BindClientEmail {
        panel_id: i64,
        telegram_user_id: i64,
    },
    BindServiceName {
        panel_id: i64,
        telegram_user_id: i64,
        client_email: String,
    },
}

#[derive(BotCommands, Clone)]
#[command(rename_rule = "lowercase", description = "Available commands:")]
enum Command {
    #[command(description = "start bot")]
    Start,
    #[command(description = "show help")]
    Help,
    #[command(description = "show status")]
    Status,
    #[command(description = "cancel current flow")]
    Cancel,
    #[command(description = "bind service: /bind <panel_id> <telegram_user_id> <client_email> [service_name]")]
    Bind(String),
    #[command(description = "force sync all")]
    SyncAll,
}

type MyDialogue = Dialogue<State, InMemStorage<State>>;

pub async fn run_bot(bot: Bot, ctx: Arc<BotContext>) {
    let storage = InMemStorage::<State>::new();

    let handler = Update::filter_message()
        .enter_dialogue::<Message, InMemStorage<State>, State>()
        .branch(dptree::entry().filter_command::<Command>().endpoint(handle_command))
        .branch(dptree::endpoint(handle_message));

    Dispatcher::builder(bot, handler)
        .dependencies(dptree::deps![storage, ctx])
        .enable_ctrlc_handler()
        .build()
        .dispatch()
        .await;
}

async fn handle_command(bot: Bot, msg: Message, dialogue: MyDialogue, cmd: Command, ctx: Arc<BotContext>) -> Result<()> {
    let user_id = msg.chat.id.0;
    match cmd {
        Command::Start => {
            upsert_user(&ctx, &msg).await;
            dialogue.update(State::Idle).await?;
            bot.send_message(msg.chat.id, "ربات آماده است.")
                .reply_markup(main_keyboard(ctx.config.is_admin(user_id)))
                .await?;
            send_status_cards(&bot, &msg, &ctx, true).await?;
        }
        Command::Help => {
            let mut text = "/start\n/status\n/help\n/cancel".to_string();
            if ctx.config.is_admin(user_id) {
                text.push_str("\n\nادمین:\n/sync_all\n/bind <panel_id> <telegram_user_id> <client_email> [service_name]");
            }
            bot.send_message(msg.chat.id, text).await?;
        }
        Command::Status => {
            send_status_cards(&bot, &msg, &ctx, true).await?;
        }
        Command::Cancel => {
            dialogue.update(State::Idle).await?;
            bot.send_message(msg.chat.id, "عملیات لغو شد.")
                .reply_markup(main_keyboard(ctx.config.is_admin(user_id)))
                .await?;
        }
        Command::SyncAll => {
            if !ctx.config.is_admin(user_id) {
                bot.send_message(msg.chat.id, "شما دسترسی ادمین ندارید.").await?;
            } else {
                if !allow_admin_action(&ctx, user_id) {
                    bot.send_message(msg.chat.id, "تعداد درخواست مدیریتی زیاد است.").await?;
                    return Ok(());
                }
                bot.send_message(msg.chat.id, "شروع همگام‌سازی...").await?;
                ctx.services.refresh_all_services().await;
                bot.send_message(msg.chat.id, "همگام‌سازی کامل شد.").await?;
                let _ = ctx
                    .services
                    .db
                    .add_audit_log(Some(user_id), "sync_all", Some("user_service"), None, true, None)
                    .await;
            }
        }
        Command::Bind(args) => {
            if !ctx.config.is_admin(user_id) {
                bot.send_message(msg.chat.id, "شما دسترسی ادمین ندارید.").await?;
            } else {
                if !allow_admin_action(&ctx, user_id) {
                    bot.send_message(msg.chat.id, "تعداد درخواست مدیریتی زیاد است.").await?;
                    return Ok(());
                }
                handle_bind_command(&bot, &msg, &ctx, &args).await?;
            }
        }
    }
    Ok(())
}

async fn handle_message(bot: Bot, msg: Message, dialogue: MyDialogue, ctx: Arc<BotContext>, state: State) -> Result<()> {
    let user_id = msg.chat.id.0;
    let text = msg.text().unwrap_or("").trim();
    match state {
        State::Idle => match text {
            "📊 وضعیت سرویس من" => {
                send_status_cards(&bot, &msg, &ctx, true).await?;
            }
            "مدیریت" => {
                if !ctx.config.is_admin(user_id) {
                    bot.send_message(msg.chat.id, "شما دسترسی ادمین ندارید.").await?;
                } else {
                    bot.send_message(msg.chat.id, "پنل مدیریت:")
                        .reply_markup(admin_keyboard())
                        .await?;
                }
            }
            "بازگشت" => {
                bot.send_message(msg.chat.id, "منوی اصلی")
                    .reply_markup(main_keyboard(ctx.config.is_admin(user_id)))
                    .await?;
            }
            "افزودن پنل" => {
                if !admin_gate(&bot, &msg, &ctx).await? {
                    return Ok(());
                }
                dialogue.update(State::AddPanelUrl).await?;
                bot.send_message(
                    msg.chat.id,
                    "لینک لاگین پنل را وارد کنید. مثال:\nhttp://HOST:PORT/WEBBASEPATH/login/",
                )
                .await?;
            }
            "لیست پنل‌ها" => {
                if !admin_gate(&bot, &msg, &ctx).await? {
                    return Ok(());
                }
                let panels = ctx.services.list_panels().await?;
                if panels.is_empty() {
                    bot.send_message(msg.chat.id, "هیچ پنلی ثبت نشده است.").await?;
                } else {
                    let mut out = String::from("پنل‌های ثبت‌شده:\n");
                    for p in panels {
                        let status = if p.last_login_ok == 1 { "✅" } else { "❌" };
                        let line = format!("ID={} | {} | {} | {}{}\n", p.id, status, p.name, p.base_url, p.web_base_path);
                        out.push_str(&line);
                    }
                    bot.send_message(msg.chat.id, out).await?;
                }
            }
            "اتصال سرویس به کاربر" => {
                if !admin_gate(&bot, &msg, &ctx).await? {
                    return Ok(());
                }
                dialogue.update(State::BindPanelId).await?;
                bot.send_message(msg.chat.id, "شناسه پنل (panel_id) را وارد کنید:").await?;
            }
            "همگام‌سازی مصرف" => {
                if !admin_gate(&bot, &msg, &ctx).await? {
                    return Ok(());
                }
                bot.send_message(msg.chat.id, "شروع همگام‌سازی...").await?;
                ctx.services.refresh_all_services().await;
                bot.send_message(msg.chat.id, "همگام‌سازی کامل شد.").await?;
            }
            _ => {}
        },
        State::AddPanelUrl => {
            dialogue
                .update(State::AddPanelUsername {
                    login_url: text.to_string(),
                })
                .await?;
            bot.send_message(msg.chat.id, "یوزرنیم پنل را وارد کنید:").await?;
        }
        State::AddPanelUsername { login_url } => {
            dialogue
                .update(State::AddPanelPassword {
                    login_url,
                    username: text.to_string(),
                })
                .await?;
            bot.send_message(msg.chat.id, "پسورد پنل را وارد کنید:").await?;
        }
        State::AddPanelPassword { login_url, username } => {
            dialogue
                .update(State::AddPanelTwoFactor {
                    login_url,
                    username,
                    password: text.to_string(),
                })
                .await?;
            bot.send_message(msg.chat.id, "twoFactorCode را وارد کنید (اگر ندارید خالی بفرستید):")
                .await?;
        }
        State::AddPanelTwoFactor {
            login_url,
            username,
            password,
        } => {
            let two_factor = if text.is_empty() { None } else { Some(text) };
            bot.send_message(msg.chat.id, "در حال تست اتصال به پنل...").await?;
            match ctx
                .services
                .add_panel(&login_url, &username, &password, two_factor, user_id)
                .await
            {
                Ok(panel_id) => {
                    let _ = ctx
                        .services
                        .db
                        .add_audit_log(Some(user_id), "add_panel", Some("panel"), Some(&panel_id.to_string()), true, None)
                        .await;
                    bot.send_message(
                        msg.chat.id,
                        format!("با موفقیت وارد شد و پنل ذخیره شد.\nشناسه پنل: {panel_id}"),
                    )
                    .reply_markup(admin_keyboard())
                    .await?;
                }
                Err(err) => {
                    let _ = ctx
                        .services
                        .db
                        .add_audit_log(Some(user_id), "add_panel", Some("panel"), None, false, Some(&err.to_string()))
                        .await;
                    bot.send_message(msg.chat.id, format!("اتصال ناموفق بود:\n{err}"))
                        .reply_markup(admin_keyboard())
                        .await?;
                }
            }
            dialogue.update(State::Idle).await?;
        }
        State::BindPanelId => match text.parse::<i64>() {
            Ok(panel_id) => {
                dialogue.update(State::BindUserId { panel_id }).await?;
                bot.send_message(msg.chat.id, "telegram_user_id کاربر را وارد کنید:").await?;
            }
            Err(_) => {
                bot.send_message(msg.chat.id, "panel_id باید عدد باشد.").await?;
            }
        },
        State::BindUserId { panel_id } => match text.parse::<i64>() {
            Ok(telegram_user_id) => {
                dialogue
                    .update(State::BindClientEmail {
                        panel_id,
                        telegram_user_id,
                    })
                    .await?;
                bot.send_message(msg.chat.id, "شناسه کانفیگ (email/client) را وارد کنید:")
                    .await?;
            }
            Err(_) => {
                bot.send_message(msg.chat.id, "telegram_user_id باید عدد باشد.").await?;
            }
        },
        State::BindClientEmail {
            panel_id,
            telegram_user_id,
        } => {
            if text.is_empty() {
                bot.send_message(msg.chat.id, "شناسه کانفیگ نمی‌تواند خالی باشد.").await?;
            } else {
                dialogue
                    .update(State::BindServiceName {
                        panel_id,
                        telegram_user_id,
                        client_email: text.to_string(),
                    })
                    .await?;
                bot.send_message(msg.chat.id, "نام سرویس را وارد کنید (اختیاری؛ برای پیش‌فرض - بزنید):")
                    .await?;
            }
        }
        State::BindServiceName {
            panel_id,
            telegram_user_id,
            client_email,
        } => {
            let service_name = if text.is_empty() || text == "-" {
                None
            } else {
                Some(text)
            };
            bot.send_message(msg.chat.id, "در حال بررسی سرویس روی پنل...").await?;
            match ctx
                .services
                .bind_service_to_user(panel_id, telegram_user_id, &client_email, service_name, None)
                .await
            {
                Ok(usage) => {
                    let _ = ctx
                        .services
                        .db
                        .add_audit_log(Some(user_id), "bind_service", Some("user_service"), Some(&usage.service_name), true, None)
                        .await;
                    bot.send_message(
                        msg.chat.id,
                        format!("سرویس با موفقیت متصل شد.\nسرویس: {}\nوضعیت: {}", usage.service_name, usage.status),
                    )
                    .reply_markup(admin_keyboard())
                    .await?;
                }
                Err(err) => {
                    let _ = ctx
                        .services
                        .db
                        .add_audit_log(Some(user_id), "bind_service", Some("user_service"), None, false, Some(&err.to_string()))
                        .await;
                    bot.send_message(msg.chat.id, format!("اتصال سرویس ناموفق بود:\n{err}"))
                        .reply_markup(admin_keyboard())
                        .await?;
                }
            }
            dialogue.update(State::Idle).await?;
        }
    }
    Ok(())
}

async fn handle_bind_command(bot: &Bot, msg: &Message, ctx: &BotContext, args: &str) -> Result<()> {
    let parts: Vec<&str> = args.split_whitespace().collect();
    if parts.len() < 3 {
        bot.send_message(
            msg.chat.id,
            "فرمت:\n/bind <panel_id> <telegram_user_id> <client_email> [service_name]",
        )
        .await?;
        return Ok(());
    }

    let panel_id = match parts[0].parse::<i64>() {
        Ok(v) => v,
        Err(_) => {
            bot.send_message(msg.chat.id, "panel_id باید عدد باشد.").await?;
            return Ok(());
        }
    };
    let telegram_user_id = match parts[1].parse::<i64>() {
        Ok(v) => v,
        Err(_) => {
            bot.send_message(msg.chat.id, "telegram_user_id باید عدد باشد.").await?;
            return Ok(());
        }
    };
    let client_email = parts[2];
    let service_name = if parts.len() > 3 {
        Some(parts[3..].join(" "))
    } else {
        None
    };

    match ctx
        .services
        .bind_service_to_user(
            panel_id,
            telegram_user_id,
            client_email,
            service_name.as_deref(),
            None,
        )
        .await
    {
        Ok(usage) => {
            bot.send_message(
                msg.chat.id,
                format!("bind موفق:\nسرویس: {}\nوضعیت: {}", usage.service_name, usage.status),
            )
            .await?;
        }
        Err(err) => {
            bot.send_message(msg.chat.id, format!("خطا در bind:\n{err}")).await?;
        }
    }
    Ok(())
}

async fn send_status_cards(bot: &Bot, msg: &Message, ctx: &BotContext, force_refresh: bool) -> Result<()> {
    let user_id = msg.chat.id.0;
    let cards = match ctx.services.get_user_status_cards(user_id, force_refresh).await {
        Ok(v) => v,
        Err(err) => {
            bot.send_message(msg.chat.id, format!("خطا در دریافت وضعیت:\n{err}"))
                .reply_markup(main_keyboard(ctx.config.is_admin(user_id)))
                .await?;
            return Ok(());
        }
    };
    if cards.is_empty() {
        bot.send_message(
            msg.chat.id,
            "سرویسی به اکانت شما متصل نشده است. برای اتصال با ادمین هماهنگ کنید.",
        )
        .reply_markup(main_keyboard(ctx.config.is_admin(user_id)))
        .await?;
        return Ok(());
    }
    for (idx, card) in cards.iter().enumerate() {
        let mut req = bot.send_message(msg.chat.id, card.clone());
        if idx == 0 {
            req = req.reply_markup(main_keyboard(ctx.config.is_admin(user_id)));
        }
        req.await?;
    }
    Ok(())
}

fn main_keyboard(is_admin: bool) -> KeyboardMarkup {
    let mut rows = vec![vec![KeyboardButton::new("📊 وضعیت سرویس من")]];
    if is_admin {
        rows.push(vec![KeyboardButton::new("مدیریت")]);
    }
    KeyboardMarkup::new(rows).resize_keyboard()
}

fn admin_keyboard() -> KeyboardMarkup {
    KeyboardMarkup::new(vec![
        vec![KeyboardButton::new("افزودن پنل"), KeyboardButton::new("لیست پنل‌ها")],
        vec![KeyboardButton::new("اتصال سرویس به کاربر"), KeyboardButton::new("همگام‌سازی مصرف")],
        vec![KeyboardButton::new("بازگشت"), KeyboardButton::new("لغو")],
    ])
    .resize_keyboard()
}

async fn upsert_user(ctx: &BotContext, msg: &Message) {
    let user_id = msg.chat.id.0;
    let full_name = msg
        .from
        .as_ref()
        .map(|u| {
            if let Some(last) = &u.last_name {
                format!("{} {}", u.first_name, last)
            } else {
                u.first_name.clone()
            }
        })
        .unwrap_or_else(|| "unknown".to_string());
    let username = msg.from.as_ref().and_then(|u| u.username.clone());
    let _ = ctx
        .services
        .db
        .upsert_user(user_id, &full_name, username.as_deref(), ctx.config.is_admin(user_id))
        .await;
}

fn allow_admin_action(ctx: &BotContext, user_id: i64) -> bool {
    ctx.limiter.allow(
        user_id,
        ctx.config.admin_rate_limit_count,
        ctx.config.admin_rate_limit_window_seconds,
    )
}

async fn admin_gate(bot: &Bot, msg: &Message, ctx: &BotContext) -> Result<bool> {
    let user_id = msg.chat.id.0;
    if !ctx.config.is_admin(user_id) {
        bot.send_message(msg.chat.id, "شما دسترسی ادمین ندارید.").await?;
        return Ok(false);
    }
    if !allow_admin_action(ctx, user_id) {
        bot.send_message(msg.chat.id, "تعداد درخواست مدیریتی زیاد است.").await?;
        return Ok(false);
    }
    Ok(true)
}
