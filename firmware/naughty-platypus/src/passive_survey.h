#ifndef NAUGHTY_PLATYPUS_PASSIVE_SURVEY_H
#define NAUGHTY_PLATYPUS_PASSIVE_SURVEY_H

#include <stdbool.h>

int np_passive_survey_start(void);
int np_passive_survey_stop(void);
int np_passive_survey_status(void);
int np_passive_survey_reset(void);
int np_passive_survey_drain(void);
int np_passive_survey_set_active(void);
int np_passive_survey_set_passive(void);
int np_passive_survey_mode_status(void);
bool np_passive_survey_is_running(void);

#endif
