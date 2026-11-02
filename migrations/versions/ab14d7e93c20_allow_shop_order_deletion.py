"""Allow assigned shop staff to delete orders and their dependent records.

Revision ID: ab14d7e93c20
Revises: d82f1b70a631
"""
from alembic import op

revision = "ab14d7e93c20"
down_revision = "d82f1b70a631"
branch_labels = None
depends_on = None


def set_delete_policies(*, allow_shop):
    if op.get_bind().dialect.name != "postgresql":
        return
    shop_check = " OR shop_id = pod_security.actor_shop()" if allow_shop else ""
    op.execute(f"""
        ALTER POLICY pod_orders_delete ON public.orders USING (
            pod_security.erases(user_id){shop_check});
    """)
    child_shop_check = " OR o.shop_id = pod_security.actor_shop()" if allow_shop else ""
    for table, prefix in (("order_items", "items"), ("payments", "payments")):
        op.execute(f"""
            ALTER POLICY pod_{prefix}_delete ON public.{table} USING (
                EXISTS (SELECT 1 FROM public.orders o WHERE o.id = order_id
                    AND (pod_security.erases(o.user_id){child_shop_check})));
        """)


def upgrade():
    set_delete_policies(allow_shop=True)


def downgrade():
    set_delete_policies(allow_shop=False)
