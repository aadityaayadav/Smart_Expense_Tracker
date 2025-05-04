import hashlib
import json
import time
from typing import Dict, List, Any
from bson.objectid import ObjectId

class Blockchain:
    def __init__(self):
        self.chain: List[Dict[str, Any]] = []
        self.transactions: List[Dict[str, Any]] = []
        self.create_genesis_block()
        self.difficulty = 4

    def create_genesis_block(self) -> None:
        genesis_block = {
            'index': 1,
            'timestamp': time.time(),
            'proof': 1,
            'previous_hash': '0',
            'transactions': []
        }
        genesis_block['hash'] = self.hash_block(genesis_block)
        self.chain.append(genesis_block)

    def get_latest_block(self) -> Dict[str, Any]:
        return self.chain[-1]

    def hash_block(self, block: Dict[str, Any]) -> str:
        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    def proof_of_work(self, previous_proof: int) -> int:
        new_proof = 1
        check_proof = False
        while not check_proof:
            hash_operation = hashlib.sha256(str(new_proof ** 2 - previous_proof ** 2).encode()).hexdigest()
            if hash_operation[:self.difficulty] == "0" * self.difficulty:
                check_proof = True
            else:
                new_proof += 1
        return new_proof

    def is_chain_valid(self) -> bool:
        for i in range(1, len(self.chain)):
            current_block = self.chain[i]
            previous_block = self.chain[i - 1]
            current_hash = self.hash_block(current_block)
            if current_block['hash'] != current_hash:
                return False
            if current_block['previous_hash'] != previous_block['hash']:
                return False
            previous_proof = previous_block['proof']
            proof = current_block['proof']
            hash_operation = hashlib.sha256(str(proof ** 2 - previous_proof ** 2).encode()).hexdigest()
            if hash_operation[:self.difficulty] != "0" * self.difficulty:
                return False
        return True

    def create_block(self, proof: int, previous_hash: str) -> Dict[str, Any]:
        block = {
            'index': len(self.chain) + 1,
            'timestamp': time.time(),
            'proof': proof,
            'previous_hash': previous_hash,
            'transactions': self.transactions.copy()
        }
        block['hash'] = self.hash_block(block)
        self.transactions = []
        self.chain.append(block)
        return block

    def add_transaction(self, transaction: Dict[str, Any]) -> str:
        serializable_transaction = {
            key: str(value) if isinstance(value, (bytes, ObjectId)) else value
            for key, value in transaction.items()
        }
        self.transactions.append(serializable_transaction)
        previous_block = self.get_latest_block()
        proof = self.proof_of_work(previous_block['proof'])
        new_block = self.create_block(proof, previous_block['hash'])
        return new_block['hash']