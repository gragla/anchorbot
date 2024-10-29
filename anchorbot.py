import streamlit as st
import lancedb
from lancedb.embeddings import get_registry
import openai
from typing import List, Dict, Set
import json
from pydantic import BaseModel
import asyncio
import instructor
from openai import AsyncOpenAI, OpenAI


async_client = instructor.patch(AsyncOpenAI())


class ExpandedQuery(BaseModel):
    variations: List[str]
    keywords: List[str]
    technical_terms: List[str]

class DocumentQuery:
    def __init__(self):
        self.db = lancedb.connect("./docs_lancedb")
        self.embed_func = get_registry().get("openai").create(name="text-embedding-3-small")
        self.available_assets = [
            table.replace('docs_', '').replace('_', ' ').title() 
            for table in self.db.table_names() 
            if table.startswith('docs_')
        ]
        
    def get_table_name(self, asset_name: str) -> str:
        """Convert asset name to table name format."""
        return f"docs_{asset_name.lower().replace(' ', '_')}"
    
    async def expand_query(self, query: str, selected_assets: List[str]) -> ExpandedQuery:
        """Generate query variations and extract key technical terms."""
        assets_str = ", ".join(selected_assets)
        prompt = f"""Given this query about {assets_str} documentation, help me expand it for better search results:

        Original Query: {query}

        1. Generate 3-4 alternative ways to ask the same question, focusing on technical terminology
        2. Extract key technical terms and concepts from the query
        3. Identify specific blockchain/Web3 technical terms that might be relevant

        Format your response as a JSON object with:
        - variations: list of alternative technical queries
        - keywords: list of key search terms
        - technical_terms: list of specific blockchain/Web3 technical terms

        Example for "How do I implement timelock?":
        {{
            "variations": [
                "What is the process for implementing timelock functionality?",
                "How to set up timelock mechanisms in smart contracts?",
                "Timelock implementation guide",
                "Technical steps for timelock integration"
            ],
            "keywords": [
                "timelock",
                "implementation",
                "smart contract",
                "delay mechanism"
            ],
            "technical_terms": [
                "timelock controller",
                "execution delay",
                "governance timelock",
                "access control"
            ]
        }}"""

        # Use the instructor client for structured output
        response = await async_client.chat.completions.create(
            model="gpt-4o-mini",
            response_model=ExpandedQuery,
            messages=[
                {"role": "system", "content": "You are a technical query expansion assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2
        )
        return response

    def search_documents(self, 
                        original_query: str, 
                        expanded_query: ExpandedQuery,
                        selected_assets: List[str], 
                        n_results_per_asset: int = 3,
                        debug: bool = False) -> tuple[List[Dict], Dict]:
        """Search for relevant documents using hybrid search with query expansion."""
        all_results = {}
        scores = {}
        
        for asset in selected_assets:
            table_name = self.get_table_name(asset)
            try:
                table = self.db.open_table(table_name)
                
                # Search with original query (highest weight)
                original_results = table.search(original_query, query_type='hybrid').limit(n_results_per_asset).to_df()
                for _, row in original_results.iterrows():
                    doc_id = f"{asset}_{row['id']}"
                    scores[doc_id] = scores.get(doc_id, 0) + 1.0
                    all_results[doc_id] = (row, asset)
                
                # Search with variations (medium weight)
                for variation in expanded_query.variations:
                    var_results = table.search(variation, query_type='hybrid').limit(n_results_per_asset).to_df()
                    for _, row in var_results.iterrows():
                        doc_id = f"{asset}_{row['id']}"
                        scores[doc_id] = scores.get(doc_id, 0) + 0.7
                        all_results[doc_id] = (row, asset)
                
                # Search with keywords and technical terms (lower weight)
                for term in expanded_query.keywords + expanded_query.technical_terms:
                    term_results = table.search(term, query_type='hybrid').limit(n_results_per_asset).to_df()
                    for _, row in term_results.iterrows():
                        doc_id = f"{asset}_{row['id']}"
                        scores[doc_id] = scores.get(doc_id, 0) + 0.5
                        all_results[doc_id] = (row, asset)
                
            except Exception as e:
                st.error(f"Error searching {asset} documentation: {str(e)}")
                continue
        
        # Sort by combined scores
        ranked_results = sorted([(doc_id, score) for doc_id, score in scores.items()], 
                              key=lambda x: x[1], reverse=True)
        
        # Convert to list of documents
        documents = []
        debug_info = {
            "original_query": original_query,
            "variations": expanded_query.variations,
            "keywords": expanded_query.keywords,
            "technical_terms": expanded_query.technical_terms,
            "document_scores": {}
        }
        
        for doc_id, score in ranked_results[:n_results_per_asset * len(selected_assets)]:
            row, asset = all_results[doc_id]
            doc = {
                'asset': asset,
                'title': row['title'],
                'content': row['content'],
                'url': row['url'],
                'score': score
            }
            documents.append(doc)
            
            if debug:
                debug_info["document_scores"][f"{asset} - {row['title']}"] = {
                    "score": score,
                    "url": row['url']
                }
        
        return documents, debug_info

def get_chatbot_response(query: str, relevant_docs: List[Dict], debug_info: Dict) -> str:
    # Group documents by asset
    docs_by_asset = {}
    for doc in relevant_docs:
        asset = doc['asset']
        if asset not in docs_by_asset:
            docs_by_asset[asset] = []
        docs_by_asset[asset].append(doc)
    
    # Construct context grouped by asset
    context_parts = []
    for asset, docs in docs_by_asset.items():
        context_parts.append(f"\n### {asset.upper()} Documentation:")
        for doc in docs:
            context_parts.append(
                f"Document: {doc['title']}\nContent: {doc['content']}\nURL: {doc['url']}"
            )
    
    context = "\n\n".join(context_parts)
    
    prompt = f"""You are a helpful assistant for Anchorage Digital Engineers in working with new digital assets and blockchain/Web3 projects. Answer the following question using only the information from the provided documentation. 
    If the answer cannot be found in the documentation, say so.
    
    When citing information, mention which project/protocol (asset) it comes from and provide the relevant documentation URL(s).
    If different protocols have different approaches, compare and contrast them.

    Query Understanding:
    - Original Query: {query}
    - Related Technical Terms: {', '.join(debug_info['technical_terms'])}
    
    Documentation Context:
    {context}

    User Question: {query}
    """
    
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful documentation assistant for Anchorage Digital engineers working on digital assets and blockchain/Web3 projects."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.0
    )
    
    return response.choices[0].message.content

async def main():
    st.set_page_config(page_title="Anchorbot", page_icon="🤖", layout="wide")
    
    st.title("Anchorbot")
    st.write("Ask questions about a digital asset")

    # Initialize document query system
    doc_query = DocumentQuery()
    
    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "selected_assets" not in st.session_state:
        st.session_state.selected_assets = doc_query.available_assets
    if "show_debug" not in st.session_state:
        st.session_state.show_debug = False

    # Sidebar for protocol selection and options
    with st.sidebar:
        st.header("Available Protocols")
        selected_assets = st.multiselect(
            "Select protocols to search:",
            options=doc_query.available_assets,
            default=st.session_state.selected_assets
        )
        st.session_state.selected_assets = selected_assets
        
        n_results = st.slider(
            "Results per protocol:",
            min_value=1,
            max_value=10,
            value=3
        )
        
        st.header("Options")
        st.session_state.show_debug = st.toggle("Show Query Debug Info", st.session_state.show_debug)
        
        if st.button("Clear Chat History"):
            st.session_state.messages = []
            st.rerun()

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "debug_info" in message and st.session_state.show_debug:
                with st.expander("Query Debug Info"):
                    st.json(message["debug_info"])

    # Chat input
    if prompt := st.chat_input("Ask a question about the selected protocols"):
        if not selected_assets:
            st.error("Please select at least one protocol to search!")
            return

        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            with st.spinner("Processing query..."):
                # Expand the query
                expanded_query = await doc_query.expand_query(prompt, selected_assets)
                
                if st.session_state.show_debug:
                    st.write("Query Expansion:")
                    st.json(expanded_query.model_dump())
                
                # Search for relevant documents
                relevant_docs, debug_info = doc_query.search_documents(
                    prompt,
                    expanded_query,
                    selected_assets,
                    n_results_per_asset=n_results,
                    debug=st.session_state.show_debug
                )
                
                # Get chatbot response
                response = get_chatbot_response(prompt, relevant_docs, debug_info)
                st.markdown(response)
                
                if st.session_state.show_debug:
                    with st.expander("Query Debug Info"):
                        st.json(debug_info)
                
                # Display relevant documents grouped by asset
                with st.expander("View Referenced Documentation"):
                    docs_by_asset = {}
                    for doc in relevant_docs:
                        asset = doc['asset']
                        if asset not in docs_by_asset:
                            docs_by_asset[asset] = []
                        docs_by_asset[asset].append(doc)
                    
                    for asset, docs in docs_by_asset.items():
                        st.subheader(f"{asset} Documentation")
                        for doc in docs:
                            st.markdown(f"### {doc['title']}")
                            st.markdown(f"Score: {doc['score']:.2f}")
                            st.markdown(f"URL: {doc['url']}")
                            st.markdown("Relevant Content:")
                            st.markdown(doc['content'])
                            st.markdown("---")

        st.session_state.messages.append({
            "role": "assistant", 
            "content": response,
            "debug_info": debug_info if st.session_state.show_debug else None
        })

if __name__ == "__main__":

    asyncio.run(main())