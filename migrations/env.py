from alembic import context
from uita.research.database import Base, Database

db = Database()
with db.engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
db.close()
