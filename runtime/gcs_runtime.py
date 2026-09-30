"""Google Cloud Storage objects (PB-064 phase 7)."""
import object_store_runtime

connector, workflow = object_store_runtime.install('gcs')
source_config, store_output, store_review = connector.source_config, connector.output, connector.review
runtime_identity = workflow.runtime_identity
if __name__ == '__main__': workflow.main()
