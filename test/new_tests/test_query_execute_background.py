# -*- coding: utf-8 -*-
import pytest
import time

import aerospike
from aerospike import exception, predexp, predicates
from aerospike_helpers.operations import operations
from aerospike import predexp as as_predexp

TEST_NS = 'test'
TEST_SET = 'background_q_e'
TEST_UDF_MODULE = 'query_apply'
TEST_UDF_FUNCTION = 'mark_as_applied'
# Hack to get long to exist in Python 3
try:
    long
except NameError:
    long = int

def wait_for_job_completion(as_connection, job_id):
    '''
    Blocks until the job has completed
    '''
    while True:
        response = as_connection.job_info(job_id, aerospike.JOB_QUERY)
        if response['status'] != aerospike.JOB_STATUS_INPROGRESS:
            break
        time.sleep(0.1)

def add_indexes_to_client(client):
    try:
        client.index_integer_create(TEST_NS, TEST_SET, 'number',
                                    'test_background_number_idx')
    except exception.IndexFoundError:
        pass

def add_test_udf(client):
    policy = {}
    client.udf_put(u"query_apply.lua", 0, policy)


def drop_test_udf(client):
    client.udf_remove("query_apply.lua")


def remove_indexes_from_client(client):
    client.index_remove(TEST_NS, 'test_background_number_idx')

def validate_records(client, keys, validator):
    for key in keys:
        _, _, rec = client.get(key)
        assert validator(rec)

# Add records around the test
@pytest.fixture(scope='function')
def clean_test_background(as_connection):
    keys = [(TEST_NS, TEST_SET, i) for i in range(500)]
    for i, key in enumerate(keys):
        as_connection.put(key, {'number': i})
    yield
    for i, key in enumerate(keys):
        as_connection.remove(key)

class TestQueryApply(object):

    # These functions will run once for this test class, and do all of the
    # required setup and teardown
    connection_setup_functions = (add_test_udf, add_indexes_to_client)
    connection_teardown_functions = (drop_test_udf, remove_indexes_from_client)

    @pytest.fixture(autouse=True)
    def setup(self, connection_with_config_funcs):
        pass

    def test_background_execute_return_val(self, clean_test_background):
        """
        Ensure that Query.execute_background() returns an int like object
        """
        test_bin = 'tz'
        query = self.as_connection.query(TEST_NS, TEST_SET)
        query.apply(TEST_UDF_MODULE, TEST_UDF_FUNCTION, [test_bin])
        res = query.execute_background()
        assert isinstance(res, (int, long))

    def test_background_execute_no_predicate(self, clean_test_background):
        """
        Ensure that Query.execute_background() gets applied to all records
        """
        test_bin = 't2222'
        keys = [(TEST_NS, TEST_SET, i) for i in range(500)]

        query = self.as_connection.query(TEST_NS, TEST_SET)
        query.apply(TEST_UDF_MODULE, TEST_UDF_FUNCTION, [test_bin])
        job_id = query.execute_background()
        # Give time for the query to finish
        
        time.sleep(5)
        #wait_for_job_completion(self.as_connection, job_id)

        validate_records(
            self.as_connection, keys,
            lambda rec: rec[test_bin] == 'aerospike'
        )

    def test_background_execute_predexp_everywhere(self, clean_test_background):
        """
        Ensure that Query.execute_background() gets applied to records that match the predexp
        """
        test_bin = 'tpred'
        keys = [(TEST_NS, TEST_SET, i) for i in range(500)]

        predexp = [
            as_predexp.integer_bin('number'),
            as_predexp.integer_value(2),
            as_predexp.integer_equal(),
            as_predexp.integer_bin('number'),
            as_predexp.integer_value(3),
            as_predexp.integer_equal(),
            as_predexp.predexp_or(2)
        ]

        #number_predicate = predicates.equals('number', 3)

        policy = {
            'predexp': predexp
        }

        query = self.as_connection.query(TEST_NS, TEST_SET)
        #query.where(number_predicate)
        query.apply(TEST_UDF_MODULE, TEST_UDF_FUNCTION, [test_bin])
        job_id = query.execute_background(policy)
        # Give time for the query to finish
        time.sleep(5)
        #wait_for_job_completion(self.as_connection, job_id)

        for key in keys:
            _, _, bins = self.as_connection.get(key)
            if bins['number'] == 2 or bins['number'] == 3:
                assert(bins[test_bin] == 'aerospike')
            else:
                assert(bins.get(test_bin) is None)

    @pytest.mark.xfail(reason="predicate and predexp used at same time")
    def test_background_execute_predexp_and_predicate(self, clean_test_background):
        """
        Ensure that Query.execute_background() gets applied to records that match the predicate
        NOTE: the predicate overrides the predexp
        """
        test_bin = 'tpredold'
        keys = [(TEST_NS, TEST_SET, i) for i in range(500)]

        predexp = [
            as_predexp.integer_bin('number'),
            as_predexp.integer_value(2),
            as_predexp.integer_equal(),
            as_predexp.integer_bin('number'),
            as_predexp.integer_value(3),
            as_predexp.integer_equal(),
            as_predexp.predexp_or(2)
        ]

        number_predicate = predicates.equals('number', 4)

        policy = {
            'predexp': predexp
        }

        query = self.as_connection.query(TEST_NS, TEST_SET)
        query.where(number_predicate)
        query.apply(TEST_UDF_MODULE, TEST_UDF_FUNCTION, [test_bin])
        query.execute_background(policy)
        # Give time for the query to finish
        time.sleep(5)

        for key in keys:
            _, _, bins = self.as_connection.get(key)
            if bins['number'] == 4:
                assert(bins[test_bin] == 'aerospike')
            else:
                assert(bins.get(test_bin) is None)

    def test_background_execute_with_ops_and_predexp(self, clean_test_background):
        """
        Ensure that Query.execute_background() applies ops to records that match the predexp
        """
        test_bin = 'tops_preds'
        keys = [(TEST_NS, TEST_SET, i) for i in range(500)]

        query = self.as_connection.query(TEST_NS, TEST_SET)
        # query.apply(TEST_UDF_MODULE, TEST_UDF_FUNCTION, [test_bin])

        ops = [
            operations.write(test_bin, 'new_val')
        ]

        predexp = [
            as_predexp.integer_bin('number'),
            as_predexp.integer_value(2),
            as_predexp.integer_equal(),
            as_predexp.integer_bin('number'),
            as_predexp.integer_value(3),
            as_predexp.integer_equal(),
            as_predexp.predexp_or(2)
        ]

        policy = {
            'predexp': predexp
        }

        query.add_ops(ops)
        query.execute_background(policy)
        # Give time for the query to finish
        time.sleep(5)

        for key in keys:
            _, _, bins = self.as_connection.get(key)
            if bins['number'] == 2 or bins['number'] == 3:
                assert(bins[test_bin] == 'new_val')
            else:
                assert(bins.get(test_bin) is None)

    def test_background_execute_with_ops(self, clean_test_background):
        """
        Ensure that Query.execute_background() applies ops to all records
        """
        test_bin = 'tops'
        keys = [(TEST_NS, TEST_SET, i) for i in range(500)]

        query = self.as_connection.query(TEST_NS, TEST_SET)
        # query.apply(TEST_UDF_MODULE, TEST_UDF_FUNCTION, [test_bin])

        ops = [
            operations.write(test_bin, 'new_val')
        ]

        query.add_ops(ops)
        query.execute_background()
        # Give time for the query to finish
        time.sleep(5)

        validate_records(
            self.as_connection, keys,
            lambda rec: rec[test_bin] == 'new_val'
        )

    def test_background_execute_with_ops_and_preds(self, clean_test_background):
        """
        Ensure that Query.execute_background() applies ops to records that match the predicate
        """
        test_bin = 't1'
        keys = [(TEST_NS, TEST_SET, i) for i in range(500)]

        query = self.as_connection.query(TEST_NS, TEST_SET)
        number_predicate = predicates.equals('number', 3)
        # query.apply(TEST_UDF_MODULE, TEST_UDF_FUNCTION, [test_bin])

        ops = [
            operations.append(test_bin, 'new_val')
        ]

        query.add_ops(ops)
        query.where(number_predicate)
        query.execute_background()
        # Give time for the query to finish
        time.sleep(5)

        _, _, num_5_record = self.as_connection.get((TEST_NS, TEST_SET, 5))
        assert num_5_record.get(test_bin) is None

        _, _, num_3_record = self.as_connection.get((TEST_NS, TEST_SET, 3))
        assert num_3_record[test_bin] == 'new_val'

        # cleanup
        ops = [
            operations.write(test_bin, 'aerospike')
        ]

        query = self.as_connection.query(TEST_NS, TEST_SET)
        query.add_ops(ops)
        query.execute_background()
        time.sleep(3)

        validate_records(
            self.as_connection, keys,
            lambda rec: rec[test_bin] == 'aerospike'
        )

    def test_background_execute_sindex_predicate(self, clean_test_background):
        """
        Ensure that Query.execute_background() only applies to records matched by
        the specified predicate
        """
        test_bin = 't3'
        keys = [(TEST_NS, TEST_SET, i) for i in range(500)]
        number_predicate = predicates.equals('number', 5)

        query = self.as_connection.query(TEST_NS, TEST_SET)
        query.where(number_predicate)
        query.apply(TEST_UDF_MODULE, TEST_UDF_FUNCTION, [test_bin])
        query.execute_background()
        # Give time for the query to finish
        time.sleep(5)
        keys = [(TEST_NS, TEST_SET, i) for i in range(500) if i != 5]
        validate_records(
            self.as_connection, keys,
            lambda rec: test_bin not in rec
        )
        _, _, num_5_record = self.as_connection.get((TEST_NS, TEST_SET, 5))
        assert num_5_record[test_bin] == 'aerospike'

    def test_background_execute_sindex_predexp(self, clean_test_background):
        """
        Ensure that Query.execute_background() only applies to records matched by
        the specified predicate
        """
        test_bin = 't4'
        keys = [(TEST_NS, TEST_SET, i) for i in range(500)]

        #  rec['number'] < 10
        predexps = [predexp.integer_bin('number'), predexp.integer_value(10), predexp.integer_less()]

        query = self.as_connection.query(TEST_NS, TEST_SET)
        query.predexp(predexps)
        query.apply(TEST_UDF_MODULE, TEST_UDF_FUNCTION, [test_bin])
        query.execute_background()
        # Give time for the query to finish
        time.sleep(5)

        # Records with number > 10 should not have had the UDF applied
        validate_records(
            self.as_connection, keys[10:],
            lambda rec: test_bin not in rec
        )
        #  Records with number < 10 should have had the udf applied
        validate_records(
            self.as_connection, keys[:10],
            lambda rec: rec[test_bin] == 'aerospike'
        )

    def test_background_execute_with_policy(self, clean_test_background):
        """
        Ensure that Query.execute_background() returns an int like object
        """
        test_bin = 't5'
        query = self.as_connection.query(TEST_NS, TEST_SET)
        query.apply(TEST_UDF_MODULE, TEST_UDF_FUNCTION, [test_bin])
        res = query.execute_background({'socket_timeout': 10000})
        assert isinstance(res, (int, long))

    def test_background_execute_with_policy_kwarg(self, clean_test_background):
        """
        Ensure that Query.execute_background() returns an int like object
        """
        test_bin = 't6'
        query = self.as_connection.query(TEST_NS, TEST_SET)
        query.apply(TEST_UDF_MODULE, TEST_UDF_FUNCTION, [test_bin])
        res = query.execute_background(policy={})
        assert isinstance(res, (int, long))

    def test_background_execute_with_invalid_policy_type(self, clean_test_background):
        """
        Ensure that Query.execute_background() returns an int like object
        """
        test_bin = 't6'
        query = self.as_connection.query(TEST_NS, TEST_SET)
        query.apply(TEST_UDF_MODULE, TEST_UDF_FUNCTION, [test_bin])
        # Policy needs to be a dict. Not a string
        with pytest.raises(exception.ParamError):
            res = query.execute_background("Honesty is the best Policy")
