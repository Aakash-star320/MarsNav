# Local AI and RAG specification

Ollama is the local inference runtime. At the event, choose one modest, locally installed model that demonstrably follows JSON/tool-call schemas on the team hardware; record model/version/RAM/latency in the demo evidence. The model is optional for core planning: map, stored routes and deterministic backend tools work without it.

The assistant supports only: extract supported objective/constraints; inspect targets/data/provenance/hazards; generate/replan routes via tools; compare returned routes; and explain returned evidence. It asks for required missing start/destination/mission context. A tool registry provides typed calls to analysis status/result, target lookup, route creation/replanning, data status, and navigation guidance. Tool calls are validated Pydantic requests and their returned structured values are copied into the response—LLM text never calculates or invents metrics/coordinates.

RAG content is locally curated NASA/PDS/USGS documentation, source product labels, target evidence and regional-analysis summaries. Use sentence-transformers embeddings with a local sqlite-vec index; store source URI, hash, chunk and index timestamp. Response citations identify retrieved records. If retrieval/tool execution fails, state that limitation and offer no fabricated citation.

Local operation requires installed model weights, embedding model, vector index and mission assets. Conversation logs exclude secrets and retain tool-call audit metadata. Unsupported general Mars claims receive a scoped limitation rather than a confident answer.
