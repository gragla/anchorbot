# Roadmap

## Anchorbot - v0.1 (Current Release)
* Onboard initial assets

## Anchorbot - v0.2
* Onboard 10 total assets
* Add in user feedback mechanism (thumbs up/down - "did we answer your question") for data flywheel and determine poor performing user query clusters, work on those
* Determine if clusters of user queries require a routing mechanism to be introduced
* Add in internal anchorage documentation, code snippets, etc to vectordb that might be helpful as context
* Add initial prompt injection guardrails


## Anchorbot - v0.3
* Onboard first set of users 
* Cluster user queries, identify low performing query clusters and prioritize based off query volume. 
* User interviews, pain points, what works/what doesn't

## Anchorbot - v0.4
* Make improvements for performance - multiple instances of vectordb, load balancing of queries, prompt caching

## Anchorbot - v1.0
* Release as full self-service chatbot for digital assets to engineers. 
* Pilot lagging adoption process for expected upcoming assets. Ingest necessary asset documentation, perform initial POC testing for that asset, and then move to prod for engineer use. Repeat process for next set of expected upcoming assets.

## Anchorbot - Ongoing
* Monitor production data for query cluster drift, poor performing clusters/queries, and take steps to increase user satisfaction on poor performing, high impact clusters through additional query routing channels/adding necessary data to vector db/user education  
* Iterate on retrieval experiments - different embedding models, routing performance, additional metadata fields, different rerankers (Cohere), etc.



