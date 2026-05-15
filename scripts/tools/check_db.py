from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

embeddings = HuggingFaceEmbeddings(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
db = Chroma(collection_name='legal_chunks', embedding_function=embeddings, persist_directory='./vector_db')

collection = db._collection
print('Total documents in vector DB:', collection.count())
print()

# Sample search
results = db.similarity_search_with_score('lao dong', k=5)
print('Top 5 for "lao dong":')
for i, (doc, score) in enumerate(results, 1):
    dieu = doc.metadata.get('dieu_so', '?')
    page = doc.metadata.get('page', '?')
    text = doc.page_content[:60].replace('\n', ' ')
    print(f'  [{i}] Dieu {dieu} | Page {page} | Score {score:.4f}')
    print(f'      Text: {text}...')
    print()
