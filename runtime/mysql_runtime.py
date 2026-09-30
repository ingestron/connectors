"""mysql tables through the reviewed snapshot workflow."""
import database_runtime

connector, workflow = database_runtime.install('mysql')
runtime_identity = workflow.runtime_identity
if __name__ == '__main__': workflow.main()
