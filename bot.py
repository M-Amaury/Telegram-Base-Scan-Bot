import requests
import emoji
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, CallbackQueryHandler

from config import TELEGRAM_BOT_TOKEN, BASESCAN_API_KEY

# Dictionnaire pour stocker les données des utilisateurs
user_data = {}

# Timestamp du bloc 0 sur Base
timestamp_bloc_0 = datetime.datetime(2023, 6, 15, 0, 35, 47).timestamp()
# Temps moyen entre les blocs de Base (approximation)
temps_moyen_entre_blocs = 2

def convertir_date_en_bloc_base(date):
    # Convertir la date en timestamp Unix
    timestamp_date = date.timestamp()
    # Calculer la différence de temps en secondes entre la date et le bloc 0
    difference_temps = timestamp_date - timestamp_bloc_0
    # Calculer le numéro de bloc approximatif en divisant par le temps moyen entre les blocs
    numero_bloc_approximatif = int(difference_temps / temps_moyen_entre_blocs)
    return numero_bloc_approximatif

# Fonction pour récupérer les transactions pour un contrat spécifique dans une plage de temps
def get_transactions(contract_address, start_time_str, end_time_str):
    start_time = datetime.datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S')
    end_time = datetime.datetime.strptime(end_time_str, '%Y-%m-%d %H:%M:%S')

    start_block = convertir_date_en_bloc_base(start_time)
    end_block = convertir_date_en_bloc_base(end_time)

    url = f'https://api.basescan.org/api?module=account&action=tokentx&contractaddress={contract_address}&startblock={start_block}&endblock={end_block}&apikey={BASESCAN_API_KEY}'
    response = requests.get(url)
    data = response.json()

    if data['status'] != '1' or 'result' not in data:
        print(f"Error fetching transactions: {data.get('message', 'Unknown error')}")
        return []

    transactions = [tx for tx in data['result'] if start_block <= int(tx['blockNumber']) <= end_block]
    for tx in transactions:
        tx['readable_time'] = datetime.datetime.fromtimestamp(int(tx['timeStamp'])).strftime('%Y-%m-%d %H:%M:%S')
        tx['value'] = float(tx['value']) / 10**18
    return transactions

# Command handler pour la commande '/start'
def start(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    user_data[user_id] = {'contracts': []}
    
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("Add New Contract", callback_data='add_contract')],
    ])
    update.message.reply_text('Please choose an option:', reply_markup=reply_markup)

# Callback pour gérer les clics sur les boutons
def button_click(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    choice = query.data

    if choice == 'add_contract':
        if len(user_data[user_id]['contracts']) < 4:
            query.message.reply_text('Please enter the contract address:')
            user_data[user_id]['current_step'] = 'enter_contract'
        else:
            query.message.reply_text('You can only add up to 4 contracts.')

    elif choice.startswith('remove_contract_'):
        contract_index = int(choice.split('_')[-1])
        del user_data[user_id]['contracts'][contract_index]
        update_contract_buttons(query.message, user_id)

    elif choice.startswith('set_start_date_'):
        contract_index = int(choice.split('_')[-1])
        query.message.reply_text('Please enter the start date (format: YYYY-MM-DD HH:MM:SS):')
        user_data[user_id]['current_step'] = f'set_start_date_{contract_index}'

    elif choice.startswith('set_end_date_'):
        contract_index = int(choice.split('_')[-1])
        query.message.reply_text('Please enter the end date (format: YYYY-MM-DD HH:MM:SS):')
        user_data[user_id]['current_step'] = f'set_end_date_{contract_index}'

    elif choice == 'analyze':
        analyze_contracts(context, user_id)
        context.bot.send_message(chat_id=user_id, text='Start analyzing common addresses, your analysis is in progress, it could take a while, please don\'t use buttons...')
        analyze_common_addresses(context, user_id)
        context.bot.send_message(chat_id=user_id, text='End analyzing the similar addresses')

        # Nouvelles conditions pour gérer la pagination
    elif choice == 'first_page':
        user_data[user_id]['current_page'] = 0
        send_current_page(context, user_id)

    elif choice == 'previous_page':
        if user_data[user_id]['current_page'] > 0:
            user_data[user_id]['current_page'] -= 1
        send_current_page(context, user_id)

    elif choice == 'current_page':
        # Do nothing as it's just to display the current page number
        pass

    elif choice == 'next_page':
        if user_data[user_id]['current_page'] < len(user_data[user_id]['pages']) - 1:
            user_data[user_id]['current_page'] += 1
        send_current_page(context,user_id)

# Handler pour les messages texte
def text_message(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    current_step = user_data.get(user_id, {}).get('current_step')

    if current_step == 'enter_contract':
        contract_address = update.message.text.strip()
        token_name = get_token_name(contract_address)
        user_data[user_id]['contracts'].append({
            'address': contract_address,
            'name': token_name,
            'start_time': None,
            'end_time': None
        })
        user_data[user_id]['current_step'] = None
        update_contract_buttons(update.message, user_id)

    elif current_step and current_step.startswith('set_start_date_'):
        contract_index = int(current_step.split('_')[-1])
        start_time_str = update.message.text
        user_data[user_id]['contracts'][contract_index]['start_time'] = start_time_str
        user_data[user_id]['current_step'] = None
        update_contract_buttons(update.message, user_id)

    elif current_step and current_step.startswith('set_end_date_'):
        contract_index = int(current_step.split('_')[-1])
        end_time_str = update.message.text
        user_data[user_id]['contracts'][contract_index]['end_time'] = end_time_str
        user_data[user_id]['current_step'] = None
        update_contract_buttons(update.message, user_id)

# Fonction pour obtenir le nom du token à partir de l'adresse du contrat (à implémenter)
def get_token_name(contract_address):
    url = f'https://api.basescan.org/api?module=token&action=tokeninfo&contractaddress={contract_address}&apikey={BASESCAN_API_KEY}'
    
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad status codes
        data = response.json()
        
        if data['status'] == '1' and 'result' in data:
            return data['result']['tokenSymbol']
        else:
            return f"{contract_address[:6]}...{contract_address[-4:]}"
    except requests.exceptions.RequestException as e:
        print(f"Error fetching token name: {e}")
        return f"Error-Token-{contract_address[:8]}"

# Fonction pour mettre à jour les boutons des contrats
def update_contract_buttons(message, user_id):
    buttons = []
    for index, contract in enumerate(user_data[user_id]['contracts']):
        start_date_text = contract['start_time'] if contract['start_time'] else "Set Start Date"
        end_date_text = contract['end_time'] if contract['end_time'] else "Set End Date"
        
        buttons.extend([
            [InlineKeyboardButton(f"{contract['name']}", callback_data=f'set_token_{index}'),
             InlineKeyboardButton(emoji.emojize(':wastebasket:') + "Remove", use_aliases=True, callback_data=f'remove_contract_{index}')],
            [InlineKeyboardButton(start_date_text, callback_data=f'set_start_date_{index}'),
             InlineKeyboardButton(end_date_text, callback_data=f'set_end_date_{index}')]
        ])
    if len(user_data[user_id]['contracts']) < 4:
        buttons.append([InlineKeyboardButton("Add New Contract", callback_data='add_contract')])
    if user_data[user_id]['contracts']:
        buttons.append([InlineKeyboardButton("Analyze", callback_data='analyze')])

    reply_markup = InlineKeyboardMarkup(buttons)
    message.reply_text('Manage your contracts:', reply_markup=reply_markup)

# Fonction pour générer les boutons de navigation
def generate_navigation_buttons(current_page, total_pages):
    buttons = [
        InlineKeyboardButton("First", callback_data='page_0'),
        InlineKeyboardButton("Previous", callback_data=f'page_{max(0, current_page - 1)}'),
        InlineKeyboardButton(f"{current_page + 1} of {total_pages}", callback_data='noop'),
        InlineKeyboardButton("Next", callback_data=f'page_{min(total_pages - 1, current_page + 1)}'),
        InlineKeyboardButton("Last", callback_data=f'page_{total_pages - 1}')
    ]
    return InlineKeyboardMarkup([buttons])


def is_contract(address):
    params = {
        'module': 'proxy',
        'action': 'eth_getCode',
        'address': address,
        'tag': 'latest',
        'apikey': BASESCAN_API_KEY
    }
    response = requests.get('https://api.basescan.org/api', params=params)
    data = response.json()
    code = data.get('result')
    return code != '0x'

# Fonction pour envoyer un rapport paginé
def send_paginated_report(context, chat_id, report_pages, current_page):
    total_pages = len(report_pages)
    if total_pages == 0:
        context.bot.send_message(chat_id=chat_id, text="No common addresses found.")
        return
    
    report_text = report_pages[current_page]
    navigation_markup = generate_navigation_buttons(current_page, total_pages)
    
    context.bot.send_message(chat_id=chat_id, text=report_text, parse_mode='Markdown', reply_markup=navigation_markup)

# Fonction pour envoyer la page courante des résultats
def send_current_page(context, user_id):
    current_page = user_data[user_id]['current_page']
    pages = user_data[user_id]['pages']
    contracts = user_data[user_id]['contracts']

    if current_page < 0 or current_page >= len(pages):
        context.bot.send_message(chat_id=user_id, text='Invalid page number.')
        return

    page_addresses = pages[current_page]
    final_report = ""

    for address in page_addresses:
        analysis_results = f"🎫 {address}\n"
        for contract in contracts:
            transactions = [tx for tx in contract['transactions'] if tx['from'].lower() == address.lower() or tx['to'].lower() == address.lower()]

            # URL DexScreener
            dexscreener_url = f"https://dexscreener.com/base/{contract['address']}?maker={address}"

            # Ajouter les informations du contrat à la chaîne de caractères
            analysis_results += (
                f"{contract['name']} - {len(transactions)} TX (timeframe)\n"
                f"[DexScreener]({dexscreener_url})\n\n"
            )

        # Ajouter les liens Debank et BaseScan
        debank_url = f"https://debank.com/profile/{address}"
        basescan_url = f"https://basescan.org/address/{address}"
        analysis_results += (
            f"🔍[Debank]({debank_url})\n"
            f"🔍 [BaseScan]({basescan_url})\n"
        )

        final_report += analysis_results + "\n"

    # Envoyer le rapport final comme un seul message
    buttons = []
    if len(pages) > 1:
        buttons.append(InlineKeyboardButton("<<", callback_data='first_page'))
        buttons.append(InlineKeyboardButton("<", callback_data='previous_page'))
        buttons.append(InlineKeyboardButton(f"{current_page + 1}/{len(pages)}", callback_data='current_page'))
        buttons.append(InlineKeyboardButton(">", callback_data='next_page'))
        buttons.append(InlineKeyboardButton(">>", callback_data='last_page'))

    reply_markup = InlineKeyboardMarkup([buttons])
    context.bot.send_message(chat_id=user_id, text=final_report, parse_mode='Markdown', reply_markup=reply_markup, disable_web_page_preview=True)


def check_wallet_in_transactions(contract_address, start_time_str, end_time_str):
    transactions = get_transactions(contract_address, start_time_str, end_time_str)
    
    if not transactions:
        print("Failed to fetch transactions.")
        return []

    addresses = set(tx['from'] for tx in transactions) | set(tx['to'] for tx in transactions)
    
    wallet_addresses = []
    for address in addresses:
        if not is_contract(address):
            wallet_addresses.append(address)
     
    return wallet_addresses

# Fonction pour analyser les transactions pour chaque contrat
def analyze_contracts(context, user_id):
    for contract in user_data[user_id]['contracts']:
        context.bot.send_message(chat_id=user_id, text=f"⏳ Start analyzing transactions for the following contract: {contract['name']}")
        transactions = get_transactions(contract['address'], contract['start_time'], contract['end_time'])
        wallets = check_wallet_in_transactions(contract['address'], contract['start_time'], contract['end_time'])
        context.bot.send_message(chat_id=user_id, text=f"🔫 Number of different addresses found: {len(wallets)}")
        contract['transactions'] = transactions
        contract['unique_addresses'] = wallets
        context.bot.send_message(chat_id=user_id, text=f"✅ End analyzing transactions for the following contract: {contract['name']}")


# Fonction pour analyser les adresses communes entre tous les contrats
def analyze_common_addresses(context, user_id):
    contracts = user_data[user_id]['contracts']
    if not contracts:
        context.bot.send_message(chat_id=user_id, text='No contracts to analyze.')
        return

    # Trouver les adresses communes
    common_addresses = set(contracts[0]['unique_addresses'])
    for contract in contracts[1:]:
        common_addresses &= set(contract['unique_addresses'])

    # Convertir l'ensemble en une liste triée pour une pagination cohérente
    sorted_addresses = sorted(common_addresses)

    # Découper les adresses en pages de 3 (par exemple, ajustez selon vos besoins)
    page_size = 3
    pages = [sorted_addresses[i:i + page_size] for i in range(0, len(sorted_addresses), page_size)]

    # Enregistrer les pages dans les données utilisateur
    user_data[user_id]['pages'] = pages
    user_data[user_id]['current_page'] = 0

    # Envoyer la première page des résultats
    send_current_page(context, user_id)

def paginate_results(results, page_size):
    return [results[i:i + page_size] for i in range(0, len(results), page_size)]

# Fonction pour diviser les résultats en pages
def page_navigation(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data.startswith('page_'):
        page_number = int(data.split('_')[1])
        user_data[user_id]['current_page'] = page_number
        
        report_pages = user_data[user_id].get('report_pages', [])
        if report_pages:
            send_paginated_report(context, user_id, report_pages, page_number)
        else:
            context.bot.send_message(chat_id=user_id, text="No report available.")


# Fonction principale pour démarrer le bot
def main() -> None:
    updater = Updater(TELEGRAM_BOT_TOKEN)
    dispatcher = updater.dispatcher

    # Ajouter les handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, text_message))
    dispatcher.add_handler(CallbackQueryHandler(button_click))
    dispatcher.add_handler(CallbackQueryHandler(page_navigation, pattern='^page_'))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
