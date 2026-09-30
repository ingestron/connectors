"""SharePoint files through Microsoft Graph (PB-064 phase 4, preview)."""
import graph_runtime

connector, workflow = graph_runtime.install('sharepoint')
source_config, graph_output, graph_review = connector.source_config, connector.output, connector.review
runtime_identity = workflow.runtime_identity
if __name__ == '__main__': workflow.main()
