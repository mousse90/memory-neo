FROM memgraph/memgraph:latest
EXPOSE 7687
CMD ["/usr/lib/memgraph/memgraph", "--bolt-server-name-for-init=Neo4j/", "--bolt-port=7687", "--bolt-address=::", "--data-directory=/var/lib/memgraph"]
