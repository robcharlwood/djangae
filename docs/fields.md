# Djangae Model Fields

## ListField / SetField

These allows you to store a list/set of values (strings, floats, integers dates) in a single field.
This is often useful when structuring data for a non-relational database. [See example usage](fields.md#example-usages).

### `ListField(item_field, **kwargs)`


* `item_field`: An instance of a Django model field which defines the data type and validation for each item in the list.
* `ordering`: A callable which allows the items in the list to be automatically sorted.

### `SetField(item_field, **kwargs)`

* `item_field`: An instance of a Django model field which defines the data type and validation for each item in the list.


Both fields also accept the following standard Django model field kwargs:

* `default`: works as normal.
* `blank`: works as normal.
* `null`: this cannot be set to `True`.  The App Engine Datastore does not allow us to differentiate between `[]` and `None`, so we stick with the former.
* `validators`: works as normal, but note that it's important where you pass this argument; if you pass it to the `ListField` or `SetField` then the validators operate on the list/set as a whole, but if you pass it to the nested model field then the validators operate on each individual value.
* `choices`: this works as normal, but should be passed to the nested model field, not to the `ListField`/`SetField` itself.  In a form this results in a multiple select field.
* `unique`: works as normal, but note that this relates to the uniqueness across different instances, not uniqueness within the list of values.  If you just want to remove duplicates from the list of values in the field then use `SetField`; setting `unique=True` will check that no 2 objects contain *any* of the same values for this field.
* `editable`: works as normal.
* `help_text`: works as normal.
* `verbose_name`: works as normal.
* `max_length`: limits the number of items allowed in the list/set.  Note that this is separate to any `max_length` that you might have on the nested `item_field`.

Both fields also accept the following additional kwargs:

* `min_length`: Set the minimum number of items allowed in the list/set.

Djangae makes some effort to provide a sensible form field for `ListField`/`SetField`, but you may find that in some cases you need to customise or change this behaviour to suit your usage.

### Querying ListField and SetField

Querying ListField and SetField is very similar to querying the PostgreSQL ArrayField which exists in recent Django versions.

There are a few custom lookups for ListField and SetField

*Note: Before Djangae 0.9.7 the syntax of these lookups was different (isnull vs isempty, exact vs contains, in vs overlap)*

#### contains

The `contains` lookup is used when you want to return instances where the specified field contains a particular value:

```
>>> Post.objects.create(name="First", tags=["one", "two"])
>>> Post.objects.create(name="Second", tags=["two", "three"])

>>> Post.objects.filter(tags__contains="one")
>>> [<Post: First>]
```

#### isempty

The `isempty` lookup returns instances where the specified field has no entries:

```
>>> Post.objects.create(name="First", tags=["one", "two"])
>>> Post.objects.create(name="Second", tags=[])

>>> Post.objects.filter(tags__isempty=True)
>>> [<Post: Second>]
```

#### overlap

The `overlap` lookup returns instances where the specified field contains one or more of the passed values:

```
>>> Post.objects.create(name="First", tags=["one", "two"])
>>> Post.objects.create(name="Second", tags=["two", "three"])

>>> Post.objects.filter(tags__overlap=["one", "two"])
>>> [<Post: First>, <Post: Second>]
>>> Post.objects.filter(tags__overlap=["one"])
>>> [<Post: First>]
```

## RelatedSetField

This is essentially a substitue for `ManyToManyField`, but which works on the non-relational App Engine Datastore.
It works by storing a list of primary keys of the related objects.  Think of it as a `SetField` with a layer of manager/query magic on top which allow you to create it much like a `ManyToManyField`. [See example usage](fields.md#example-usages).

```RelatedSetField(related_model, **kwargs)```

* `model`: the model of the related items.
* `limit_choices_to`: a dictionary of query kwargs for limiting the possible related items.
* `related_name` - the name of the reverse lookup attribute which is added to the model class of the related items.


The `RelatedSetField` also accepts most of the same kwargs as `SetField`.

The value of a `RelatedSetField` is a hybrid of a `QuerySet` and a `set`, and has the following methods:

* `add(obj)` - takes a Django model instance and adds it to the set.  The instance must be of the same type as the `model` argument of the `RelatedSetField` and must be saved.
* `remove(obj)` - takes a Django model instances and removes it from the set.  The instance must be of the same type as the `model` argument of the `RelatedSetField` and must be saved.
* `clear()` - removes all values from the set.

Note that (unlike a `ManyToManyField`) you must call `save()` on the object for the effects of the above method calls to be saved to the database.

The value of a `RelatedSetField` also has all of the methods of a normal `QuerySet` such as `.filter()`, `.get()`, `.update()`, `.delete()` etc.

### Additional Notes

* If you delete any of the objects in the set (whether by calling `.delete()` on the field or by calling `.delete()` on objects individually), the IDs of the objects will still be stored in the field, even though they will never be returned (because they don't exist).  You should remove them from the field using `remove(obj)` or `clear()`.
* You can access the underlying `set` which contains the IDs of the related objects.  Similar to how a `ForeignKey` field stores its ID in a `<field_name>_id` attribute, the `RelatedSetField` stores the IDs in a `<field_name>_ids` attribute.  You can access and manipulate this value manually.  For example, if you want to add an object to the set and you know its ID but don't have the actual instance and don't want to fetch it from the DB, you can do `my_obj.my_related_set_field_ids.add(new_id)`.
* Because the `RelatedSetField` stores the IDs of objects, its queryset is immediately consistent, i.e. is unaffected by the Datastore's eventual consistency.  For example, `my_obj.my_related_set_field.filter(colour="blue")` will always return the latest versions of those objects.

## RelatedListField

RelatedListField shares the same behavior as RelatedSetField but has the qualities of a list; it maintains the ordering of related objects and allows duplicates.

The field value still has the same `add`, `remove` and `clear` methods as the RelatedSetField, but the `add` method acts like `append` (because it's a `list` rather than a `set`).

The underlying `<field_name>_ids` attribute is a `list`.


## ShardedCounterField

This field allows you to store a counter which can be incremented/decremented at an extremely high rate without causing database contention.  Given that the Datastore is not performant at doing `count()` queries, this is an excellent way of counting large numbers on the Datastore. [See example usage](fields.md#example-usages).

It works by creating a set of `CounterShard` objects, each of which stores a count, and each time you call `.increment()` or `.decrement()` on the field it randomly picks one of its `CounterShard` objects to increment or decrement.  When you call `.value()` on the field it sums the counts of all the shards to give you the total.  The more shards you specify the higher the rate at which it can handle `.increment()`/`.decrement()` calls.

```ShardedCounterField(shard_count=24, related_name="+", **kwargs)```

* `shard_count`: the number of `CounterShard` objects to use.  The default number is deliberately set to allow all of the shards to be created (and the object to which they belong updated) in a single transaction.  See the `.populate()` method below.
* `related_name`: the name of the reverse relation lookup which is added to the `CounterShard` model.  This is deliberately set to `"+"` to avoid the reverse lookup being set, as in most cases you will never need it and setting it gives you the problem of avoiding clashes when you have multiple ShardedCounterFields on the same model.

When you access the attribute of your sharded counter field on your model, you get a `RelatedShardManager` object, which has the following API:

* `.value()`: Gives you the value of counter.  This is immediately consistent (i.e. is not affected by the Datastore's eventual consistency behaviour).
* `.increment(step=1)`: Transactionally increment the counter by the given step.
    - If you have not yet called `.populate()` then this might also cause your model object to be re-saved, depending on whether or not it needs to create a new shard.
* `.decrement(step=1)`: Transactionally decrement the counter by the given step.
    - If you have not yet called `.populate()` then this might also cause your model object to be re-saved, depending on whether or not it needs to create a new shard.
* `.populate()`: Creates all the shards that the counter will need.
     - This is useful if you want to ensure that additional saves to your model object are avoided when calling `.increment()` or `.decrement()`, as these saves may cause issues if you're doing things inside a transaction or at such a rate that they cause DB contention on your model object.
     - Note that this causes your model instance to be re-saved.
* `.reset()`: Resets the counter to 0.
    - This is done by changing the value of the shards, not by deleting them.  So you can continue to use your counter afterwards without having to call `populate()` again first.
* `.shard_count()`: Gives the number of `CounterShard` objects which are being used to store the counter.

### Callback function

If you want to perform some actions after a sharded counter was changed you can provide `on_change` argument with a function to call.

```your_field = ShardedCounterField(on_change=your_callback_function)```

The callback function takes two arguments: `instance`, `step` and optional `is_reset`, where instance is the instance of the object with the `ShardedCounterField`, `step` informs us how much the counter was changed and `is_reset` lets us know if the counter was reset.

```python
def your_callback_function(instance, step, is_reset=False):
    ...
```

The function will be called every time you run `increment`, `decrement` and `reset`.


### Additional notes:

* Counts can be negative.
* `ShardedCounterField` is a subclass of `RelatedSetField`, so in addition to the above API you also have the manager methods from `RelatedSetField` such as `.filter()`, etc.  These probably aren't very useful though!
* For convenience (or more likely, disaster recovery), each `CounterShard` has a `label` field which contains a reference to the model and field for which it is used in the format `"db_table.field_name"`.  So should you ever need to go and actually look at/alter the `CounterShard` objects, you can see which ones are used for what.


## GenericRelationField

This is a replacement for Django's `GenericForeignKey` field, which doesn't use Django's contenttypes, and consequently it allows querying by the related object even on the non-relational Datastore.  (Django's `GenericForeignKey` would cause a JOIN if you tried to do do that.)

This field requires no special kwargs, and should accept all standard Django field kwargs as normal.

## CharField

This is a replacement for Django's `CharField` field. It uses the `MaxBytesValidator` validator that makes sure the value does not exceed the hard datastore limit of 1500 bytes (see `google.appengine.api.datastore_types _MAX_STRING_LENGTH`). Use this field whenever you're planning to store large char values in the datastore, else your data may get silently trimmed.

## JSONField

This field is not specific to the App Engine Datastore (or any non-relational database), but is included in Djangae for convenience, especially as in a non-relational database it's often useful to be able to store structured data in a single table rather than in a complex structure of related tables.

```JSONField(use_ordered_dict=False, default=dict, **kwargs)```

* `use_ordered_dict`: (default: False).  Tells the field to maintain the order of keys in the object by using `collections.OrderedDict` for the Python representation, rather than `dict`.
* `default`: (default: dict).  A callable which returns or creates the default value.  E.g. `dict` or `list`.  Do not use `{}` or `[]`.


Note that if you want to edit JSONField values in the Django admin, you must set `formfield_overrides` on your ModelAdmin class.  Otherwise converting to/from JSON will not happen correctly.  E.g.:

```python
from djangae.forms.fields import JSONWidget

class MyModelAdmin(admin.ModelAdmin):
    formfield_overrides = {
        JSONField: {'widget': JSONWidget(attrs={'class': 'vLargeTextField'})},
    }
```

If a JSONField is set to blank=False, then any form submitted value must be a valid JSON object which is not empty (e.g. not `{}` or `[]`) if
  a JSONField is nullable and blank=True then a None will be saved in the empty case. An empty string is not a valid value for a JSONField.

### Querying

You can query JSONField contents using a similar format to the that used by Django's [PostgreSQL JSONField](https://docs.djangoproject.com/en/1.10/ref/contrib/postgres/fields/#querying-jsonfield).
Only direct path lookups are implemented, so no `contains`, `contained_by`, `has_key` etc.

There are some limitations:

 - The only possible lookups are 'exact' lookups, or `isnull`
 - If a path contains an integer, it's assumed to be an integer index into a list (you can't query a key of "1" for example)
 - You can't query paths where the final part of the path is "isnull"... for obvious reasons
 - Paths must be added to djangaeidx.yaml (automatic after first use) and your entities must be resaved for the queries to return values

## TrueOrNullField

This field is not specific to the App Engine Datastore (or any non-relational database), but is included in Djangae for convenience.

Its primary use case is for when you want a boolean field which can only be set to true for *one* object.  This is done by making use of the fact that Django (and most databases) ignore `None` values in unique constraints, so by having a field which can only store values of `True` or `None` and by setting the field to unique, you get a field which can only be `True` on one object.


## Computed Fields

These fields allow you to have a value which is computed from other fields values when an instance is saved.
This can be particularly useful with the Datastore where there are limitations to queries.
For example, you can't do `.filter(a__gte=x, b__gte=y)`, but if `x` and `y` are constant then you could add a computed field which stores a boolean value to indicate whether or not an object meets these criteria.
So you could then do `.filter(a_is_gte_x_and_b_is_gte_y=True)`.

Each computed field takes a single argument of a "computer" function.  This can be passed either as a callable object, or as a string containing the name of a method on the model. This "computer" function or method is called each time the model instance is saved, with the model instance passed as a single argument (this is just the normal `self` in the case of a method).
The value which the function returns is what is stored in the computed field.

Computed fields are:

* `ComputedCharField`
* `ComputedTextField`
* `ComputedIntegerField`
* `ComputedPositiveIntegerField`
* `ComputedBooleanField`
* `ComputedNullBooleanField`


## FileField & ImageField

Djangae provides custom versions of Django's `FileField` and `ImageField`, which provide the normal behaviour but additionally accept an optional `url_field` argument to allow you to specify the name of another field on the model on which the URL to the file or image is cached.

If you're using the Cloud Storage or Blobstore storage backend, then this caching of the URL allows you to avoid the underlying call to App Engine's `get_serving_url` function each time you access the URL, as that can cause significant slowness.

The cached URL value in your specified field is updated each time the file/image is created or modified.

## Example Usages


```
from django.db import models
from djangae import fields


class Kitten(models.Model):
    image = fields.ImageField(url_field="image_url")
    image_url = fields.CharField()
    
    
class KittenSanctuary(models.Model):

    is_best = fields.TrueOrNullField(unique=True)
    kittens = fields.RelatedSetField('Kitten')
    kitten_rota = fields.RelatedListField('Kitten')
    inspection_dates = fields.SetField(models.DateField())
    historic_weekly_kitten_count = fields.ListField(models.PositiveIntegerField())
    number_of_meows = fields.ShardedCounterField()
    current_staff_rota = fields.JSONField()
    number_of_meows_is_greater_than_sum_of_weekly_kitten_counts = ComputedBooleanField(
        lambda self: self.number_of_meows > sum(self.historic_weekly_kitten_count)
    )


def new_kitten_arrival(sanctuary, kitten):
    sanctuary.kittens.add(kitten)
    sanctuary.save()

def log_inspection(sanctuary):
    sanctuary.inspection_dates.add(timezone.now())
    sanctuary.save()

def log_meow(sanctuary):
    sanctuary.number_of_meows.increment()
    # Note that we don't need to save the object
    print sanctuary.number_of_meows.value()
```

## djangae.fields.language.ComputedCollationField

This is a specialized computed field which is used so you can have correct alphabetical ordering of non-ASCII strings.

*Note: use of this field requires the 'pyuca' package be installed*

### Explanation

SQL databases (such as MySQL) use various 'collations' for determining how one string is ordered relative to another. The Datastore
does not have this functionality. On the Datastore all strings are ordered by their unicode code point, which means that non-ASCII characters
are always ordered after ASCII ones, and the ordering of unicode chars is not alphabetical.

This means that if you (for example) want to order users by their first name this would give the wrong result:

```
   User.objects.create(first_name="Vera")
   User.objects.create(first_name="Łukasz")
   User.objects.order_by("first_name")
```

ComputedCollationField fixes this by calculating a suitable 'sort key' from the source value, you would then use the
ComputedCollationField when specifying the order. For example:

```
from djangae.fields import CharField, ComputedCollationField

class User(models.Model):
    first_name = CharField() # This is the field you work with
    first_name_order = ComputedCollationField('first_name') # This is what you order by

User.objects.order_by("first_name_order") # Now correctly orders alphabetically
```

