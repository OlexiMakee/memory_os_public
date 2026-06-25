import time
from memory_os.core.config import MemoryOSConfig
from memory_os.modules.search import MemorySearcher
config = MemoryOSConfig()
searcher = MemorySearcher(config)

t0 = time.time()
res1 = searcher.search_memory("test")
t1 = time.time()
print(f"First search: {t1-t0:.4f}s, hits: {len(res1)}")

t2 = time.time()
res2 = searcher.search_memory("test")
t3 = time.time()
print(f"Second search: {t3-t2:.4f}s, hits: {len(res2)}")
