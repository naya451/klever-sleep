#include <ldv/linux/common.h>
#include <ldv/linux/err.h>
#include <ldv/verifier/common.h>
#include <ldv/verifier/nondet.h>

extern int ldv_exclusive_spin_is_locked(void);
extern int ldv_is_rw_locked(void);

void ldv_common_sleep(void)
{
	if (ldv_exclusive_spin_is_locked())
		/* ASSERT shouldnt sleep in spinlock*/
		ldv_assert();
    if (ldv_in_interrupt_context())
		/* ASSERT shouldnt sleep in interrupt context*/
		ldv_assert();
  	if (ldv_is_rw_locked()) 
      /* ASSERT shouldnt sleep in rwlock*/
      ldv_assert();
}
