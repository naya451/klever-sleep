/*
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * ee the License for the specific language governing permissions and
 * limitations under the License.
 */

/* The test should check processing of function pointers with different declarations */

#include <linux/module.h>
#include <linux/mutex.h>
#include <verifier/nondet.h>
#include <verifier/thread.h>

static DEFINE_MUTEX(ldv_lock);
static int _ldv_safe;
static int _ldv_unsafe;

static int ldv_func(void)
{
    _ldv_safe = 1;
    _ldv_unsafe = 1;
    return 0;
}

static void* ldv_control_function(void *arg)
{
    ldv_func();
    return NULL;
}

static int __init ldv_init(void)
{
	pthread_t thread1;
	pthread_attr_t const *attr1 = ldv_undef_ptr();
	void *arg1 = ldv_undef_ptr();
	void *status;

	pthread_create(&thread1, attr1, &ldv_control_function, arg1);
    _ldv_unsafe = 0;
    pthread_join(&thread1, &status);
    _ldv_safe = 0;
	return 0;
}

module_init(ldv_init);
