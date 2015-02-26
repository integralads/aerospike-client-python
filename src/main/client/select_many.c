/*******************************************************************************
 * Copyright 2013-2014 Aerospike, Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 ******************************************************************************/

#include <Python.h>
#include <stdbool.h>

#include <aerospike/aerospike_key.h>
#include <aerospike/aerospike_batch.h>
#include <aerospike/as_key.h>
#include <aerospike/as_error.h>
#include <aerospike/as_record.h>
#include <aerospike/as_batch.h>

#include "client.h"
#include "conversions.h"
#include "key.h"
#include "policy.h"

// Callback method
static bool batch_select_cb(const as_batch_read* results, uint32_t n, void* udata)
{
	// Typecast udata back to PyObject
	PyObject * py_recs = (PyObject *) udata;

	// Initialize error object
	as_error err;

	as_error_init(&err);

	// Loop over results array
	for ( uint32_t i =0; i < n; i++ ){

		// Check record status
		if ( results[i].result == AEROSPIKE_OK ){

			PyObject * rec = NULL;
			PyObject * p_key = NULL;

			switch(((as_val*)(results[i].key->valuep))->type){
				case AS_INTEGER:
					p_key = PyInt_FromLong((long)results[i].key->value.integer.value);

					break;
				case AS_STRING:
					p_key = PyString_FromString((const char *)results[i].key->value.string.value);
					break;
				default:
					break;
			}

			record_to_pyobject(&err, &results[i].record, results[i].key, &rec);

			// Set return value in return Dict
			if ( PyDict_SetItem( py_recs, p_key, rec ) ){
				return false;
			}
			Py_DECREF(rec);
			Py_DECREF(p_key);
		}
	}
	return true;
}

static
PyObject * AerospikeClient_Select_Many_Invoke(
	AerospikeClient * self,
	PyObject * py_keys, PyObject * py_bins, PyObject * py_policy)
{
	// Python Return Value
	PyObject * py_recs = PyDict_New();

	// Aerospike Client Arguments
	as_error err;
	as_batch batch;
	as_policy_batch policy;
	as_policy_batch * batch_policy_p = NULL;
	Py_ssize_t bins_size = 0;
	char **filter_bins = NULL;

	// Initialisation flags
	bool batch_initialised = false;

	// Initialize error
	as_error_init(&err);

	// Convert python keys list to as_key ** and add it to as_batch.keys
	// keys can be specified in PyList or PyTuple
	if ( py_keys != NULL && PyList_Check(py_keys) ) {
		Py_ssize_t size = PyList_Size(py_keys);

		as_batch_init(&batch, size);
		// Batch object initialised
		batch_initialised = true;

		for ( int i = 0; i < size; i++ ) {

			PyObject * py_key = PyList_GetItem(py_keys, i);

			if ( !PyTuple_Check(py_key) ){
				as_error_update(&err, AEROSPIKE_ERR_CLIENT, "Key should be a tuple.");
				goto CLEANUP;
			}

			pyobject_to_key(&err, py_key, as_batch_keyat(&batch, i));

			if ( err.code != AEROSPIKE_OK ) {
				goto CLEANUP;
			}
		}
	}
	else if ( py_keys != NULL && PyTuple_Check(py_keys) ) {
		Py_ssize_t size = PyTuple_Size(py_keys);

		as_batch_init(&batch, size);
		// Batch object initialised.
		batch_initialised = true;

		for ( int i = 0; i < size; i++ ) {
			PyObject * py_key = PyTuple_GetItem(py_keys, i);

			if ( !PyTuple_Check(py_key) ){
				as_error_update(&err, AEROSPIKE_ERR_CLIENT, "Key should be a tuple.");
				goto CLEANUP;
			}

			pyobject_to_key(&err, py_key, as_batch_keyat(&batch, i));

			if ( err.code != AEROSPIKE_OK ) {
				goto CLEANUP;
			}
		}
	}
	else {
		as_error_update(&err, AEROSPIKE_ERR_CLIENT, "Keys should be specified as a list or tuple.");
		goto CLEANUP;
	}

	// Check the type of bins and get it's size
	// i.e. number of bins provided
	if (py_bins != NULL && PyList_Check(py_bins)){
		bins_size    = PyList_Size(py_bins);
	}
	else if (py_bins != NULL && PyTuple_Check(py_bins)){
		bins_size    = PyTuple_Size(py_bins);
	}
	else {
		as_error_update(&err, AEROSPIKE_ERR_CLIENT, "Filter bins should be specified as a list or tuple.");
		goto CLEANUP;
	}

	filter_bins = (char **)malloc(sizeof(long int) * bins_size);

	for (int i = 0; i < bins_size; i++){
		PyObject *py_bin = NULL;
		if(PyList_Check(py_bins)){
			py_bin = PyList_GetItem(py_bins, i);
		}
		if(PyTuple_Check(py_bins)){
			py_bin = PyTuple_GetItem(py_bins, i);
		}
		filter_bins[i]    = PyString_AsString(py_bin);
	}

	// Convert python policy object to as_policy_batch
	pyobject_to_policy_batch(&err, py_policy, &policy, &batch_policy_p);
	if ( err.code != AEROSPIKE_OK ) {
		goto CLEANUP;
	}

	// Invoke C-client API
	aerospike_batch_get_bins(self->as, &err, batch_policy_p,
		&batch, filter_bins, bins_size, (aerospike_batch_read_callback) batch_select_cb,
		py_recs);

CLEANUP:

	if (filter_bins != NULL){
		free(filter_bins);
	}

	if (batch_initialised == true){
		// We should destroy batch object as we are using 'as_batch_init' for initialisation
		// Also, pyobject_to_key is soing strdup() in case of Unicode. So, object destruction
		// is necessary.
		as_batch_destroy(&batch);
	}

	if ( err.code != AEROSPIKE_OK ) {
		PyObject * py_err = NULL;
		error_to_pyobject(&err, &py_err);
		PyErr_SetObject(PyExc_Exception, py_err);
		Py_DECREF(py_err);
		return NULL;
	}

	return py_recs;
}

PyObject * AerospikeClient_Select_Many(AerospikeClient * self, PyObject * args, PyObject * kwds)
{
	// Python Function Arguments
	PyObject * py_keys = NULL;
	PyObject * py_bins = NULL;
	PyObject * py_policy = NULL;

	// Python Function Keyword Arguments
	static char * kwlist[] = {"keys", "bins", "policy", NULL};

	// Python Function Argument Parsing
	if ( PyArg_ParseTupleAndKeywords(args, kwds, "OO|O:select_many", kwlist, 
					 &py_keys, &py_bins, &py_policy) == false ) {
		return NULL;
	}

	// Invoke Operation
	return AerospikeClient_Select_Many_Invoke(self, py_keys, py_bins, py_policy);
}
