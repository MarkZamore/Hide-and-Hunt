package lanminecraft.hideandhunt.mixin;

import de.hideandhunt.client.screen.CreateWorldView;
import org.spongepowered.asm.mixin.Mixin;

@Mixin(value = CreateWorldView.class, remap = false)
abstract class CreateWorldViewMixin {
}
