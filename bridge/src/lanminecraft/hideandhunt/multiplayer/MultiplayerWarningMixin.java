package lanminecraft.hideandhunt.multiplayer;

import net.minecraft.client.Options;
import net.minecraft.client.gui.screens.TitleScreen;
import org.objectweb.asm.Opcodes;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Redirect;

@Mixin(value = TitleScreen.class, remap = false)
abstract class MultiplayerWarningMixin {
    @Redirect(
        method = "lambda$createNormalMenuOptions$3(Lnet/minecraft/client/gui/components/Button;)V",
        at = @At(value = "FIELD", target = "Lnet/minecraft/client/Options;skipMultiplayerWarning:Z",
            opcode = Opcodes.GETFIELD),
        require = 1,
        allow = 1
    )
    private boolean hideAndHunt$skipThirdPartyServerWarning(Options options) {
        return true;
    }
}
