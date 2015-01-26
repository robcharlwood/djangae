from djangae.contrib import sleuth
from django.db import models
from django.core.cache import cache
from djangae.test import TestCase
from djangae.db import unique_utils
from djangae.db import transaction
from djangae.db.backends.appengine.context import ContextStack
from google.appengine.api import datastore

class FakeEntity(dict):
    COUNTER = 1

    def __init__(self, data):
        self.update(data)

    def key(self):
        try:
            return datastore.Key.from_path("table", FakeEntity.COUNTER)
        finally:
            FakeEntity.COUNTER += 1


class ContextStackTests(TestCase):

    def test_push_pop(self):
        stack = ContextStack()

        self.assertEqual({}, stack.top.cache)

        entity = FakeEntity({"bananas": 1})

        stack.top.cache_entity(["bananas:1"], entity)

        self.assertEqual({"bananas": 1}, stack.top.cache.values()[0])

        stack.push()

        self.assertEqual({"bananas": 1}, stack.top.cache.values()[0])
        self.assertEqual(2, stack.size)

        stack.push()

        stack.top.cache_entity(["apples:2"], entity)

        self.assertItemsEqual(["bananas:1", "apples:2"], stack.top.cache.keys())

        stack.pop()

        self.assertItemsEqual(["bananas:1"], stack.top.cache.keys())
        self.assertEqual({"bananas": 1}, stack.top.cache["bananas:1"])
        self.assertEqual(2, stack.size)
        self.assertEqual(1, stack.staged_count)

        updated = FakeEntity({"bananas": 3})

        stack.top.cache_entity(["bananas:1"], updated)

        stack.pop(apply_staged=True, clear_staged=True)

        self.assertEqual(1, stack.size)
        self.assertEqual({"bananas": 3}, stack.top.cache["bananas:1"])
        self.assertEqual(0, stack.staged_count)

    def test_property_deletion(self):
        stack = ContextStack()

        entity = FakeEntity({"field1": "one", "field2": "two"})

        stack.top.cache_entity(["entity"], entity)

        stack.push() # Enter transaction

        entity["field1"] = "oneone"
        del entity["field2"]

        stack.top.cache_entity(["entity"], entity)

        stack.pop(apply_staged=True, clear_staged=True)

        self.assertEqual({"field1": "oneone"}, stack.top.cache["entity"])



class CachingTestModel(models.Model):

    field1 = models.CharField(max_length=255, unique=True)
    comb1 = models.IntegerField(default=0)
    comb2 = models.CharField(max_length=255)

    class Meta:
        unique_together = [
            ("comb1", "comb2")
        ]


class MemcacheCachingTests(TestCase):
    """
        We need to be pretty selective with our caching in memcache, because unlike
        the context caching, this stuff is global.

        For that reason, we have the following rules:

         - save/update caches entities outside transactions
         - Inside transactions save/update wipes out the cache for updated entities (a subsequent read by key will populate it again)
         - Inside transactions filter/get does not hit memcache (that just breaks transactions)
         - filter/get by key caches entities (consistent)
         - filter/get by anything else does not (eventually consistent)
    """

    def test_save_caches_outside_transaction_only(self):
        entity_data = {
            "field1": "Apple",
            "comb1": 1,
            "comb2": "Cherry"
        }

        identifiers = unique_utils.unique_identifiers_from_entity(CachingTestModel, FakeEntity(entity_data))

        for identifier in identifiers:
            self.assertIsNone(cache.get(identifier))

        instance = CachingTestModel.objects.create(**entity_data)

        for identifier in identifiers:
            self.assertEqual(entity_data, cache.get(identifier))

        instance.delete()

        for identifier in identifiers:
            self.assertIsNone(cache.get(identifier))


        with transaction.atomic():
            instance = CachingTestModel.objects.create(**entity_data)


        for identifier in identifiers:
            self.assertIsNone(cache.get(identifier))

    def test_save_wipes_entity_from_cache_inside_transaction(self):
        entity_data = {
            "field1": "Apple",
            "comb1": 1,
            "comb2": "Cherry"
        }

        identifiers = unique_utils.unique_identifiers_from_entity(CachingTestModel, FakeEntity(entity_data))

        for identifier in identifiers:
            self.assertIsNone(cache.get(identifier))

        instance = CachingTestModel.objects.create(**entity_data)

        for identifier in identifiers:
            self.assertEqual(entity_data, cache.get(identifier))

        with transaction.atomic():
            instance.save()

        for identifier in identifiers:
            self.assertIsNone(cache.get(identifier))

    def test_consistent_read_updates_memcache_outside_transaction(self):
        entity_data = {
            "field1": "Apple",
            "comb1": 1,
            "comb2": "Cherry"
        }

        identifiers = unique_utils.unique_identifiers_from_entity(CachingTestModel, FakeEntity(entity_data))

        for identifier in identifiers:
            self.assertIsNone(cache.get(identifier))

        CachingTestModel.objects.create(**entity_data)

        for identifier in identifiers:
            self.assertEqual(entity_data, cache.get(identifier))

        cache.clear()

        for identifier in identifiers:
            self.assertIsNone(cache.get(identifier))

        CachingTestModel.objects.get() # Consistent read

        for identifier in identifiers:
            self.assertEqual(entity_data, cache.get(identifier))

    def test_eventual_read_doesnt_update_memcache(self):
        entity_data = {
            "field1": "Apple",
            "comb1": 1,
            "comb2": "Cherry"
        }

        identifiers = unique_utils.unique_identifiers_from_entity(CachingTestModel, FakeEntity(entity_data))

        for identifier in identifiers:
            self.assertIsNone(cache.get(identifier))

        CachingTestModel.objects.create(**entity_data)

        for identifier in identifiers:
            self.assertEqual(entity_data, cache.get(identifier))

        cache.clear()

        for identifier in identifiers:
            self.assertIsNone(cache.get(identifier))

        CachingTestModel.objects.all()[0] # Inconsistent read

        for identifier in identifiers:
            self.assertIsNone(cache.get(identifier))

    def test_unique_filter_hits_memcache(self):
        entity_data = {
            "field1": "Apple",
            "comb1": 1,
            "comb2": "Cherry"
        }

        original = CachingTestModel.objects.create(**entity_data)

        with sleuth.watch("google.appengine.api.datastore.Query.Run") as datastore_query:
            instance = CachingTestModel.objects.filter(field1="Apple").all()[0]
            self.assertEqual(original, instance)

        self.assertFalse(datastore_query.called)

    def test_non_unique_filter_hits_datastore(self):
        entity_data = {
            "field1": "Apple",
            "comb1": 1,
            "comb2": "Cherry"
        }

        original = CachingTestModel.objects.create(**entity_data)

        with sleuth.watch("google.appengine.api.datastore.Query.Run") as datastore_query:
            instance = CachingTestModel.objects.filter(comb1=1).all()[0]
            self.assertEqual(original, instance)

        self.assertTrue(datastore_query.called)

    def test_get_by_key_hits_memcache(self):
        entity_data = {
            "field1": "Apple",
            "comb1": 1,
            "comb2": "Cherry"
        }

        original = CachingTestModel.objects.create(**entity_data)

        with sleuth.watch("google.appengine.api.datastore.Get") as datastore_get:
            instance = CachingTestModel.objects.get(pk=original.pk)
            self.assertEqual(original, instance)

        self.assertFalse(datastore_get.called)

    def test_get_by_key_hits_datastore_inside_transaction(self):
        entity_data = {
            "field1": "Apple",
            "comb1": 1,
            "comb2": "Cherry"
        }

        original = CachingTestModel.objects.create(**entity_data)

        with sleuth.watch("google.appengine.api.datastore.Get") as datastore_get:
            with transaction.atomic():
                instance = CachingTestModel.objects.get(pk=original.pk)
            self.assertEqual(original, instance)

        self.assertTrue(datastore_get.called)

    def test_unique_get_hits_memcache(self):
        entity_data = {
            "field1": "Apple",
            "comb1": 1,
            "comb2": "Cherry"
        }

        original = CachingTestModel.objects.create(**entity_data)

        with sleuth.watch("google.appengine.api.datastore.Get") as datastore_get:
            instance = CachingTestModel.objects.get(field1="Apple")
            self.assertEqual(original, instance)

        self.assertFalse(datastore_get.called)

    def test_unique_get_hits_datastore_inside_transaction(self):
        entity_data = {
            "field1": "Apple",
            "comb1": 1,
            "comb2": "Cherry"
        }

        original = CachingTestModel.objects.create(**entity_data)

        with sleuth.watch("google.appengine.api.datastore.Get") as datastore_get:
            with transaction.atomic():
                instance = CachingTestModel.objects.get(field1="Apple")
            self.assertEqual(original, instance)

        self.assertTrue(datastore_get.called)

class ContextCachingTests(TestCase):
    """
        We can be a bit more liberal with hitting the context cache as it's
        thread-local and request-local

        The context cache is actually a stack. When you start a transaction we push a
        copy of the current context onto the stack, when we finish a transaction we pop
        the current context and apply the changes onto the outer transaction.

        The rules are thus:

        - Entering a transaction pushes a copy of the current context
        - Rolling back a transaction pops the top of the stack
        - Committing a transaction pops the top of the stack, and adds it to a queue
        - When all transactions exit, the queue is applied to the current context one at a time
        - save/update caches entities
        - filter/get by key caches entities (consistent)
        - filter/get by anything else does not (eventually consistent)
    """

    def test_transactions_get_their_own_context(self):
        with sleuth.watch("djangae.db.backends.appengine.context.ContextStack.push") as context_push:
            with transaction.atomic():
                pass

            self.assertTrue(context_push.called)

    def test_nested_transaction_doesnt_apply_to_outer_context(self):
        pass

    def test_outermost_transaction_applies_all_contexts_on_commit(self):
        pass

    def test_nested_rollback_doesnt_apply_on_outer_commit(self):
        pass

    def test_context_wiped_on_rollback(self):
        pass

    def test_save_caches(self):
        pass

    def test_consistent_read_updates_cache(self):
        pass

    def test_inconsistent_read_doesnt_update_cache(self):
        pass

    def test_unique_filter_hits_cache(self):
        pass

    def test_get_by_key_hits_cache(self):
        pass

    def test_unique_get_hits_cache(self):
        pass
