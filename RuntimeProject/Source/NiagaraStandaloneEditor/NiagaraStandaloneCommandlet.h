#pragma once
#include "Commandlets/Commandlet.h"
#include "NiagaraStandaloneCommandlet.generated.h"

UCLASS()
class UNiagaraStandaloneCommandlet : public UCommandlet
{
    GENERATED_BODY()
public:
    UNiagaraStandaloneCommandlet();
    virtual int32 Main(const FString& Params) override;
};
