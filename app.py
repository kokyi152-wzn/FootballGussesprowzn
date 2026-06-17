# webhook function ကို ဒီလိုပြင်ပါ
@app.route('/webhook', methods=['POST'])
def webhook():
    global loop
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, telegram_app.bot)
        if loop is not None:
            future = asyncio.run_coroutine_threadsafe(telegram_app.process_update(update), loop)
            try:
                # timeout ကို 10 စက္ကန့်ကနေ 30 စက္ကန့်ထားပါ
                future.result(timeout=30)
            except TimeoutError:
                logger.error("Update processing timed out after 30 seconds")
                return "timeout", 500
            except Exception as e:
                logger.exception(f"Error processing update: {e}")
                return "error", 500
            return "ok", 200
        else:
            logger.error("Loop is None!")
            return "error", 500
    except Exception as e:
        logger.exception("Webhook error")
        return "error", 500
