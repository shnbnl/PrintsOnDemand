"""PostgreSQL private-row policies; SQLite authorization stays in the app.

Revision ID: d82f1b70a631
Revises: c19a6e72d440
"""
from alembic import op

revision = "d82f1b70a631"
down_revision = "c19a6e72d440"
branch_labels = None
depends_on = None

POLICY_SQL = """
CREATE SCHEMA pod_security;
REVOKE ALL ON SCHEMA pod_security FROM PUBLIC;
GRANT USAGE ON SCHEMA pod_security TO PUBLIC;

CREATE FUNCTION pod_security.actor_id() RETURNS bigint
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog AS $$
    SELECT NULLIF(current_setting('pod.user_id', true), '')::bigint
$$;
CREATE FUNCTION pod_security.actor_role() RETURNS text
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog AS $$
    SELECT u.role::text FROM public.users u
    WHERE u.id = pod_security.actor_id() AND u.is_active
$$;
CREATE FUNCTION pod_security.actor_shop() RETURNS bigint
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog AS $$
    SELECT u.shop_id::bigint FROM public.users u
    JOIN public.printing_shops s ON s.id = u.shop_id
    WHERE u.id = pod_security.actor_id() AND u.is_active
      AND u.role = 'SHOP_STAFF' AND s.is_active
$$;
CREATE FUNCTION pod_security.owns(owner_id bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog AS $$
    SELECT COALESCE(owner_id = pod_security.actor_id()
      AND pod_security.actor_role() IN ('STUDENT', 'PROFESSOR'), false)
$$;
CREATE FUNCTION pod_security.erasure_valid() RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog AS $$
    SELECT EXISTS (
      SELECT 1 FROM public.users target
      WHERE target.id = NULLIF(current_setting('pod.erase_user_id', true), '')::bigint
        AND target.role IN ('STUDENT', 'PROFESSOR') AND (
          target.id = pod_security.actor_id()
          OR pod_security.actor_role() = 'ADMIN'
          OR (target.role = 'PROFESSOR' AND pod_security.actor_role() = 'SHOP_STAFF'
            AND EXISTS (SELECT 1 FROM public.printing_shops s
              WHERE s.id = pod_security.actor_shop() AND s.name = 'Blue and Silver Bookstore'))
        )
    )
$$;
CREATE FUNCTION pod_security.erases(owner_id bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog AS $$
    SELECT COALESCE(owner_id = NULLIF(current_setting('pod.erase_user_id', true), '')::bigint
      AND pod_security.erasure_valid(), false)
$$;
CREATE FUNCTION pod_security.unlinks_professor(profile_id bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog AS $$
    SELECT pod_security.erasure_valid() AND EXISTS (
      SELECT 1 FROM public.users target
      WHERE target.id = NULLIF(current_setting('pod.erase_user_id', true), '')::bigint
        AND target.professor_id = profile_id
    )
$$;
CREATE FUNCTION pod_security.order_access(owner_id bigint, store_id bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog AS $$
    SELECT COALESCE(pod_security.owns(owner_id) OR pod_security.actor_role() = 'ADMIN'
      OR store_id = pod_security.actor_shop() OR pod_security.erases(owner_id), false)
$$;

ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.orders FORCE ROW LEVEL SECURITY;
CREATE POLICY pod_orders_read ON public.orders FOR SELECT USING (
  pod_security.order_access(user_id, shop_id) OR pod_security.erasure_valid());
CREATE POLICY pod_orders_create ON public.orders FOR INSERT WITH CHECK (pod_security.owns(user_id));
CREATE POLICY pod_orders_update ON public.orders FOR UPDATE
  USING (pod_security.order_access(user_id, shop_id) OR pod_security.unlinks_professor(professor_id))
  WITH CHECK (pod_security.order_access(user_id, shop_id) OR pod_security.erasure_valid());
CREATE POLICY pod_orders_delete ON public.orders FOR DELETE USING (pod_security.erases(user_id));

ALTER TABLE public.order_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.order_items FORCE ROW LEVEL SECURITY;
CREATE POLICY pod_items_read ON public.order_items FOR SELECT USING (
  EXISTS (SELECT 1 FROM public.orders o WHERE o.id = order_id));
CREATE POLICY pod_items_delete ON public.order_items FOR DELETE USING (
  EXISTS (SELECT 1 FROM public.orders o WHERE o.id = order_id AND pod_security.erases(o.user_id)));

-- This non-inlined, invoker function keeps the read-policy dependency acyclic
-- when an item INSERT checks ownership of its file. It never bypasses RLS.
CREATE FUNCTION pod_security.staff_file_access(file_id bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = pg_catalog AS $$
    SELECT pod_security.actor_role() = 'SHOP_STAFF' AND EXISTS (
      SELECT 1 FROM public.order_items i JOIN public.orders o ON o.id = i.order_id
      WHERE i.uploaded_file_id = file_id AND o.shop_id = pod_security.actor_shop()
    )
$$;
ALTER TABLE public.uploaded_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.uploaded_files FORCE ROW LEVEL SECURITY;
CREATE POLICY pod_files_read ON public.uploaded_files FOR SELECT USING (
  pod_security.owns(user_id) OR pod_security.actor_role() = 'ADMIN'
  OR pod_security.erases(user_id) OR pod_security.staff_file_access(id));
CREATE POLICY pod_files_create ON public.uploaded_files FOR INSERT WITH CHECK (pod_security.owns(user_id));
CREATE POLICY pod_files_update ON public.uploaded_files FOR UPDATE
  USING (pod_security.owns(user_id)) WITH CHECK (pod_security.owns(user_id));
CREATE POLICY pod_files_delete ON public.uploaded_files FOR DELETE
  USING (pod_security.owns(user_id) OR pod_security.erases(user_id));

CREATE POLICY pod_items_create ON public.order_items FOR INSERT WITH CHECK (
  EXISTS (SELECT 1 FROM public.orders o JOIN public.uploaded_files f ON f.id = uploaded_file_id
    WHERE o.id = order_id AND pod_security.owns(o.user_id) AND f.user_id = o.user_id));
-- No UPDATE policy: a placed item's printing/price snapshot is immutable.

ALTER TABLE public.payments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payments FORCE ROW LEVEL SECURITY;
CREATE POLICY pod_payments_read ON public.payments FOR SELECT USING (
  EXISTS (SELECT 1 FROM public.orders o WHERE o.id = order_id)
  OR pod_security.erasure_valid());
CREATE POLICY pod_payments_create ON public.payments FOR INSERT WITH CHECK (
  EXISTS (SELECT 1 FROM public.orders o WHERE o.id = order_id AND pod_security.owns(o.user_id)));
CREATE POLICY pod_payments_update ON public.payments FOR UPDATE
  USING (EXISTS (SELECT 1 FROM public.orders o WHERE o.id = order_id) OR pod_security.erases(reviewed_by_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.orders o WHERE o.id = order_id) OR pod_security.erasure_valid());
CREATE POLICY pod_payments_delete ON public.payments FOR DELETE USING (
  EXISTS (SELECT 1 FROM public.orders o WHERE o.id = order_id AND pod_security.erases(o.user_id)));

ALTER TABLE public.print_configurations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.print_configurations FORCE ROW LEVEL SECURITY;
CREATE POLICY pod_config_read ON public.print_configurations FOR SELECT USING (
  EXISTS (SELECT 1 FROM public.uploaded_files f WHERE f.id = file_id));
CREATE POLICY pod_config_create ON public.print_configurations FOR INSERT WITH CHECK (
  EXISTS (SELECT 1 FROM public.uploaded_files f WHERE f.id = file_id AND pod_security.owns(f.user_id)));
CREATE POLICY pod_config_update ON public.print_configurations FOR UPDATE
  USING (EXISTS (SELECT 1 FROM public.uploaded_files f WHERE f.id = file_id AND pod_security.owns(f.user_id)))
  WITH CHECK (EXISTS (SELECT 1 FROM public.uploaded_files f WHERE f.id = file_id AND pod_security.owns(f.user_id)));
CREATE POLICY pod_config_delete ON public.print_configurations FOR DELETE USING (
  EXISTS (SELECT 1 FROM public.uploaded_files f WHERE f.id = file_id
    AND (pod_security.owns(f.user_id) OR pod_security.erases(f.user_id))));
"""


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute(POLICY_SQL)


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in ("print_configurations", "payments", "uploaded_files", "order_items", "orders"):
        # Explicitly remove only this migration's policies, then its helper schema.
        names = {
            "print_configurations": ("read", "create", "update", "delete"),
            "payments": ("read", "create", "update", "delete"),
            "uploaded_files": ("read", "create", "update", "delete"),
            "order_items": ("read", "create", "delete"),
            "orders": ("read", "create", "update", "delete"),
        }[table]
        prefix = {"print_configurations": "config", "uploaded_files": "files", "order_items": "items"}.get(table, table)
        for suffix in names:
            op.execute(f"DROP POLICY pod_{prefix}_{suffix} ON public.{table}")
        op.execute(f"ALTER TABLE public.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")
    # CASCADE is intentionally avoided: unrelated future policies must not be removed.
    for function in ("staff_file_access(bigint)", "order_access(bigint,bigint)",
                     "unlinks_professor(bigint)", "erases(bigint)", "erasure_valid()",
                     "owns(bigint)", "actor_shop()", "actor_role()", "actor_id()"):
        op.execute(f"DROP FUNCTION pod_security.{function}")
    op.execute("DROP SCHEMA pod_security")
