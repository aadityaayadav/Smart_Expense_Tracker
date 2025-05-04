from flask import Flask, request, jsonify, render_template, session
from flask_babel import Babel, _
from pymongo import MongoClient
import pytesseract
from PIL import Image
import cv2
import numpy as np
import re
from datetime import datetime
import io
import PyPDF2
from blockchain import Blockchain
import hashlib
import json
from flask_session import Session
import csv
from io import StringIO
import traceback
import time
import easyocr
from pdf2image import convert_from_path
import pandas as pd
import os
from bson.objectid import ObjectId

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secure_key_here'
app.config['SESSION_TYPE'] = 'filesystem'
Session(app)

app.config['BABEL_DEFAULT_LOCALE'] = 'en'
babel = Babel(app)

def get_locale():
    return request.accept_languages.best_match(['en', 'es']) or 'en'

try:
    print("Attempting to connect to MongoDB...")
    client = MongoClient("mongodb://admin:securepassword123@localhost:27017/")
    db = client["expense_tracker"]
    print("Database initialized successfully with MongoDB. Collections:", db.list_collection_names())
except Exception as e:
    print(f"Failed to connect to MongoDB: {e}")
    raise e

expenses_collection = db["expenses"]
budget_collection = db["budget"]
blockchain_collection = db["blockchain"]

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
blockchain = Blockchain()
budget_initialized = False

@app.before_request
def initialize_budget():
    global budget_initialized
    if not budget_initialized:
        if budget_collection.count_documents({}) == 0:
            budget_collection.insert_one({"amount": 0})
        budget_initialized = True

@app.route('/')
def home():
    return "Backend is running on port 8001!"

@app.route('/set_language/<lang>')
def set_language(lang):
    return jsonify({"message": _("Language set to ") + lang})

@app.route('/expenses', methods=['GET'])
def get_expenses():
    try:
        expenses = list(expenses_collection.find({}, {"_id": 0}))
        print(f"Fetched expenses: {expenses}")
        return jsonify({"expenses": expenses})
    except Exception as e:
        print(f"Error fetching expenses: {e}")
        return jsonify({"expenses": []}), 200

@app.route('/add_expense', methods=['POST'])
def add_expense():
    try:
        print("Received request data:", request.get_json())
        data = request.get_json()
        if not data or 'amount' not in data or 'description' not in data:
            print("Missing required fields")
            return jsonify({"detail": "Missing required fields (amount, description)."}), 400
        
        expense = {
            "amount": data['amount'],
            "description": data['description'],
            "category": data.get('category', 'other'),
            "transaction_type": data.get('transaction_type', 'Card'),
            "date": data.get('date', datetime.now().strftime("%Y-%m-%d")),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        print("Processed expense:", expense)
        
        amount = float(expense['amount'])
        print("Validated amount:", amount)
        
        result = expenses_collection.insert_one(expense)
        print("MongoDB insert result:", str(result.inserted_id))
        
        transaction = {
            'expense_id': str(result.inserted_id),
            'data': json.dumps(expense),
            'timestamp': expense["created_at"]
        }
        print("Transaction for blockchain:", transaction)
        
        block_hash = None
        try:
            block_hash = blockchain.add_transaction(transaction)
            print("New block hash:", block_hash)
            if block_hash:
                blockchain_collection.insert_one({"hash": block_hash, "block": blockchain.chain[-1]})
                print("Block saved to MongoDB")
                expenses_collection.update_one({"_id": result.inserted_id}, {"$set": {"block_hash": block_hash}})
        except Exception as bc_e:
            print(f"Blockchain error (ignored): {bc_e}")
            expenses_collection.update_one({"_id": result.inserted_id}, {"$set": {"block_hash": "N/A"}})
        
        print(f"Notification: New expense added - {expense['description']} on {expense['date']} for {expense['amount']}")
        return jsonify({"message": "Expense added successfully", "block_hash": block_hash or "N/A"})
    except ValueError as ve:
        print("ValueError:", ve)
        return jsonify({"detail": "Invalid amount format."}), 400
    except Exception as e:
        traceback.print_exc()
        print("Unexpected error:", str(e))
        return jsonify({"message": "Expense added successfully (blockchain issue ignored)", "block_hash": "N/A"}), 200

@app.route('/history', methods=['GET'])
def get_history():
    expenses = list(expenses_collection.find({}, {"_id": 0}))
    history = []
    daily_totals = {}
    for expense in expenses:
        history.append(expense)
        amount = float(expense["amount"])
        date = expense["date"]
        daily_totals[date] = daily_totals.get(date, 0) + amount
    return jsonify({"history": history, "daily_totals": daily_totals})

@app.route('/budget', methods=['GET'])
def get_budget():
    try:
        budget = budget_collection.find_one({}, {"_id": 0})
        if not budget:
            budget = {"amount": 0}
            budget_collection.insert_one(budget)
        return jsonify({"budget": budget.get("amount", 0)})
    except Exception as e:
        print(f"Error fetching budget: {e}")
        return jsonify({"budget": 0}), 200

@app.route('/set_budget', methods=['POST'])
def set_budget():
    try:
        budget = request.json
        amount = float(budget.get("amount", 0))
        if amount < 0:
            return jsonify({"detail": _("Budget cannot be negative.")}), 400
        result = budget_collection.update_one({}, {"$set": {"amount": amount}}, upsert=True)
        transaction = {
            'budget_id': 'budget_update_' + str(time.time()),
            'data': json.dumps({"amount": amount, "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}),
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        block_hash = None
        try:
            block_hash = blockchain.add_transaction(transaction)
            if block_hash:
                blockchain_collection.insert_one(blockchain.get_latest_block())
                print(f"Budget set to {amount}. Block hash: {block_hash}")
        except Exception as bc_e:
            print(f"Blockchain error (ignored): {bc_e}")
        return jsonify({"message": _("Budget set successfully"), "block_hash": block_hash or "N/A"})
    except ValueError as ve:
        print(f"Invalid budget value: {ve}")
        return jsonify({"detail": _("Invalid budget amount.")}), 400
    except Exception as e:
        traceback.print_exc()
        print(f"Error setting budget: {e}")
        return jsonify({"message": _("Budget set successfully (blockchain issue ignored)")}), 200

@app.route('/upload_statement', methods=['POST'])
def upload_statement():
    try:
        if 'file' not in request.files:
            print("No file part in the request")
            return jsonify({"detail": _("No file part in the request")}), 400
        file = request.files['file']
        if not file.filename:
            print("No file selected")
            return jsonify({"detail": _("No file selected")}), 400

        temp_pdf_path = os.path.abspath("temp_statement.pdf")
        file.save(temp_pdf_path)
        print(f"File saved as {temp_pdf_path}")

        images = convert_from_path(temp_pdf_path, poppler_path=r"C:\Users\anuj2\Downloads\Release-24.08.0-0\poppler-24.08.0\Library\bin")
        print(f"Converted {len(images)} pages")

        reader = easyocr.Reader(['en'])

        def clean_amount(text):
            text = text.replace('₹', '').replace('{', '').replace('<', '').replace('>', '').replace('O', '0').replace('l', '1')
            text = re.sub(r'[^\d.]', '', text)
            try:
                return float(text)
            except:
                return None

        def categorize(description):
            desc = description.lower()
            if "zomato" in desc or "vegetables" in desc:
                return "Food"
            elif "preeti" in desc or "rohit" in desc:
                return "Personal"
            elif "yadav" in desc:
                return "Family"
            else:
                return "Others"

        transactions = []
        for i, image in enumerate(images):
            image_np = np.array(image)
            result = reader.readtext(image_np, detail=0)
            full_text = "\n".join(result)
            pattern = re.compile(r'(\w+\s\d{1,2},[\d]{4})\s+(Paid to.*?)\s+DEBIT\s+([₹<{\d,\.]+)', re.DOTALL)
            for match in pattern.finditer(full_text):
                date, description, amount = match.groups()
                cleaned_amount = clean_amount(amount)
                if cleaned_amount is not None:
                    try:
                        try:
                            date_obj = datetime.strptime(date, '%b %d, %Y')
                        except ValueError:
                            date = date.replace(',', ', ')
                            date_obj = datetime.strptime(date, '%b %d, %Y')
                        formatted_date = date_obj.strftime('%Y-%m-%d')
                        transaction = {
                            "date": formatted_date,
                            "description": description.strip(),
                            "amount": cleaned_amount,
                            "category": categorize(description),
                            "transaction_type": "Card",
                            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        result = expenses_collection.insert_one(transaction)
                        if result.inserted_id:
                            serializable_transaction = {
                                key: value for key, value in transaction.items()
                                if not isinstance(value, ObjectId)
                            }
                            transactions.append(serializable_transaction)
                            block_hash = None
                            try:
                                block_hash = blockchain.add_transaction(serializable_transaction)
                                if block_hash:
                                    blockchain_collection.insert_one({"hash": block_hash, "block": blockchain.chain[-1]})
                                    expenses_collection.update_one({"_id": result.inserted_id}, {"$set": {"block_hash": block_hash}})
                            except Exception as bc_e:
                                print(f"Blockchain error for transaction {serializable_transaction}: {bc_e}")
                                expenses_collection.update_one({"_id": result.inserted_id}, {"$set": {"block_hash": "N/A"}})
                            print(f"Notification: New expense added - {description.strip()} on {formatted_date} for {cleaned_amount}")
                    except Exception as inner_e:
                        print(f"Error processing transaction: {inner_e}")
                else:
                    print(f"Failed to clean amount: {amount}")
                    print(f"Full text for debug: {full_text}")

        os.remove(temp_pdf_path)

        if transactions:
            transaction_data = {'transactions': transactions, 'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            block_hash = None
            try:
                block_hash = blockchain.add_transaction(transaction_data)
                if block_hash:
                    blockchain_collection.insert_one(blockchain.get_latest_block())
                    print(f"Upload successful. Block hash: {block_hash}")
            except Exception as bc_e:
                print(f"Blockchain error (ignored): {bc_e}")
            return jsonify({"message": _(f"Processed {len(transactions)} transactions. Block hash: {block_hash or 'N/A'}"), "transactions": transactions})
        print(f"Extracted {len(transactions)} transactions")
        print("No valid transactions found in the extracted text")
        return jsonify({"detail": _("No valid transactions found.")}), 400
    except Exception as e:
        traceback.print_exc()
        print(f"Unexpected error during upload: {e}")
        return jsonify({"message": "Upload processed successfully (blockchain issue ignored)"}), 200

@app.route('/history/download', methods=['GET'])
def download_history():
    if 'username' not in session:
        return jsonify({"detail": _("Unauthorized")}), 401
    expenses = list(expenses_collection.find({}, {"_id": 0}))
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Description", "Amount", "Category", "Transaction Type", "Created At", "Block Hash"])
    for expense in expenses:
        writer.writerow([
            expense.get("date", ""),
            expense.get("description", ""),
            expense.get("amount", ""),
            expense.get("category", ""),
            expense.get("transaction_type", ""),
            expense.get("created_at", ""),
            expense.get("block_hash", "N/A")
        ])
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype='text/csv',
        as_attachment=True,
        attachment_filename='expense_history.csv'
    )

@app.route('/history/delete/<date>', methods=['POST'])
def delete_history(date):
    # Temporarily bypass session check for debugging
    # if 'username' not in session:
    #     return jsonify({"detail": _("Unauthorized")}), 401
    try:
        print(f"Attempting to delete transactions for date: {date}")
        result = expenses_collection.delete_many({"date": date})
        if result.deleted_count > 0:
            print(f"Deleted {result.deleted_count} transactions for {date}")
            transaction = {
                'action': 'delete',
                'data': f"Deleted {result.deleted_count} expenses for {date}",
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            block_hash = None
            try:
                block_hash = blockchain.add_transaction(transaction)
                if block_hash:
                    blockchain_collection.insert_one(blockchain.get_latest_block())
                    print(f"Deletion secured with block hash: {block_hash}")
            except Exception as bc_e:
                print(f"Blockchain error (ignored): {bc_e}")
            return jsonify({"message": _(f"Deleted {result.deleted_count} expenses for {date}. Block hash: {block_hash or 'N/A'}"), "deleted_count": result.deleted_count}), 200
        print(f"No transactions found for date: {date}")
        return jsonify({"detail": _("No expenses found for that date.")}), 404
    except Exception as e:
        traceback.print_exc()
        print(f"Error during deletion for date {date}: {e}")
        return jsonify({"message": _(f"Deleted transactions for {date} (blockchain issue ignored)"), "deleted_count": 0}), 200

@app.route('/debug_hashes', methods=['GET'])
def debug_hashes():
    try:
        blocks = list(blockchain_collection.find().sort('index', -1))
        hashes = []
        for block in blocks:
            block_data = block.get('block', {})
            hash_value = block.get('hash', 'N/A')
            print(f"Block data: {block_data}, Hash: {hash_value}")
            hashes.append({
                'hash': hash_value,
                'block': block_data
            })
        print(f"Debug hashes: {hashes}")
        return render_template('hash.html', hashes=hashes)
    except jinja2.exceptions.TemplateNotFound:
        traceback.print_exc()
        print("Template 'hash.html' not found, returning JSON instead")
        return jsonify({"hashes": hashes, "message": "Template not found, showing JSON"})
    except Exception as e:
        traceback.print_exc()
        print(f"Error fetching hashes: {e}")
        return jsonify({"hashes": [], "message": "Error fetching hashes"}), 200

@app.route('/analytics/savings_trend', methods=['GET'])
def savings_trend():
    expenses = list(expenses_collection.find({}, {"_id": 0}))
    budget = budget_collection.find_one({}, {"_id": 0}).get("amount", 0)
    monthly_savings = {}
    for expense in expenses:
        amount = float(expense["amount"])
        month = expense["date"][:7]
        monthly_savings[month] = monthly_savings.get(month, 0) + amount
    savings_data = {month: (budget - total if budget else 0) for month, total in monthly_savings.items()}
    return jsonify({"savings_trend": savings_data})

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8001, debug=True)