from datetime import datetime, timezone
import unittest
from app.freshness_notifications import reconcile_inbox


class FreshnessInboxTest(unittest.TestCase):
    def test_outage_delivery_dedup_recovery_and_recurrence(self):
        now = datetime.now(timezone.utc)
        incident = {'assistant_id':'synthetic-project','last_success_at':'yesterday',
                    'is_freshness_alert':True,'status':'open'}
        preferences, count = reconcile_inbox({'theme':'honey'}, [incident], now=now)
        self.assertEqual(1, count)
        self.assertEqual('honey', preferences['theme'])
        preferences['global_notifications'][0]['read'] = True
        unchanged, count = reconcile_inbox(preferences, [incident], now=now)
        self.assertEqual(0, count)
        self.assertEqual(preferences, unchanged)
        recovered, count = reconcile_inbox(preferences, [], now=now)
        self.assertEqual(1, count)
        self.assertEqual('collection_recovered', recovered['global_notifications'][0]['message_key'])
        _, count = reconcile_inbox(recovered, [incident], now=now)
        self.assertEqual(1, count)

    def test_closed_or_non_freshness_incidents_never_deliver(self):
        _, count = reconcile_inbox({}, [{'assistant_id':'x','is_freshness_alert':True,'status':'closed'},
                                        {'assistant_id':'y','status':'open'}], now=datetime.now(timezone.utc))
        self.assertEqual(0, count)
